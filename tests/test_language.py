"""Sprache Deutsch/Englisch (HKA-101): Wahl im Cookie, Weitergabe als Accept-Language, ui_locales, Anmeldeseite."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import fakeredis
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import pytest

from gateway.app import create_app
from gateway.config import OidcConfig, Settings
from gateway.language import DEFAULT_LANGUAGE, LANGUAGES, pick_language
from gateway.redirects import sanitize_return

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "keycloak" / "theme" / "hka" / "login"


class IdpStub:
    """OIDC-Client, der nur die Adresse der Anmeldung liefert und die Parameter merkt."""
    def __init__(self):
        self.calls = []

    def authorization_url(self, **kwargs):
        self.calls.append(kwargs)
        return "https://idp.test/login?ui_locales=" + str(kwargs.get("ui_locales"))


@pytest.fixture
def gateway(tmp_path):
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_file = tmp_path / "gateway.pem"
    key_file.write_bytes(signing.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    cfg = Settings("http://localhost:18080",
                   OidcConfig("http://localhost:18180/realms/test", "gateway", "test-only",
                              "http://localhost:18080/oidc/callback", "http://localhost:18080/"),
                   key_file, cookie_secure=False, cookie_name="test_sid", login_cookie="test_login")
    idp = IdpStub()
    app = create_app(cfg, redis_client=fakeredis.FakeRedis(decode_responses=True), oidc_client=idp)
    with TestClient(app, base_url=cfg.public_url, follow_redirects=False) as client:
        yield client, cfg, idp


@pytest.mark.parametrize("cookie, header, expected", [
    (None, None, "de"), (None, "", "de"), (None, "en", "en"), (None, "en-GB,en;q=0.9,de;q=0.8", "en"),
    (None, "de-DE,de;q=0.9,en;q=0.8", "de"), (None, "fr,en;q=0.5", "en"), (None, "fr-CH,fr;q=0.9", "de"),
    (None, "*", "de"), (None, "en;q=0", "de"), (None, "en;q=abc", "de"), (None, "en;q=inf", "de"),
    (None, "de;q=0.5,en;q=0.9", "en"), ("en", "de", "en"), ("de", "en", "de"), ("fr", "en", "en"), ("", None, "de"),
    (None, "en," * 200, "de"),
])
def test_pick_language(cookie, header, expected):
    assert pick_language(cookie, header) == expected


def test_sanitize_return():
    assert sanitize_return("/_portal/admin?x=1") == "/_portal/admin?x=1"
    for bad in (None, "", "https://evil.example", "//evil.example", "/\\evil", "/a\nb", "evil", "/" + "a" * 600):
        assert sanitize_return(bad) == "/"


def test_default_cookie_name_follows_secure_flag(gateway):
    _client, cfg, _idp = gateway
    assert cfg.lang_cookie == "hka_gateway_lang"
    secure = Settings(cfg.public_url, cfg.oidc, cfg.signing_key, cookie_secure=True)
    assert secure.lang_cookie == "__Host-hka_gateway_lang"


def test_switch_sets_cookie_and_returns(gateway):
    client, cfg, _idp = gateway
    r = client.get("/sprache/en", params={"next": "/_portal/admin?x=1"})
    assert r.status_code == 303 and r.headers["location"] == "/_portal/admin?x=1"
    cookie = r.headers["set-cookie"]
    assert f"{cfg.lang_cookie}=en" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Max-Age=31536000" in cookie and "Path=/" in cookie


@pytest.mark.parametrize("code", ["fr", "EN", "de-DE", "xx"])
def test_unknown_language_is_404_without_cookie(gateway, code):
    r = gateway[0].get(f"/sprache/{code}")
    assert r.status_code == 404 and "set-cookie" not in r.headers


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example", "/\\evil.example", "javascript:alert(1)"])
def test_foreign_next_goes_home(gateway, target):
    r = gateway[0].get("/sprache/en", params={"next": target})
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_switch_needs_no_login(gateway):
    assert gateway[0].get("/sprache/de").status_code == 303


def test_login_sends_ui_locales(gateway):
    client, cfg, idp = gateway
    client.get("/login")
    assert idp.calls[-1]["ui_locales"] == "de"
    client.get("/login", headers={"Accept-Language": "en-GB,en;q=0.9"})
    assert idp.calls[-1]["ui_locales"] == "en"
    client.cookies.set(cfg.lang_cookie, "de")
    client.get("/login", headers={"Accept-Language": "en"})
    assert idp.calls[-1]["ui_locales"] == "de"
    client.cookies.set(cfg.lang_cookie, "../../etc")
    client.get("/login", headers={"Accept-Language": "en"})
    assert idp.calls[-1]["ui_locales"] == "en"


def test_authorization_url_carries_ui_locales():
    from gateway.oidc import OidcClient
    import httpx

    issuer = "http://idp.test/realms/x"

    def idp(request):
        return httpx.Response(200, json={"issuer": issuer, "authorization_endpoint": issuer + "/auth",
                                         "token_endpoint": issuer + "/token", "jwks_uri": issuer + "/certs"})

    client = OidcClient(OidcConfig(issuer, "gateway", "s", "http://gw/oidc/callback", "http://gw/"),
                        httpx.Client(transport=httpx.MockTransport(idp)))
    with_locale = parse_qs(urlsplit(client.authorization_url(state="s", nonce="n", verifier="v", ui_locales="en")).query)
    assert with_locale["ui_locales"] == ["en"]
    without = parse_qs(urlsplit(client.authorization_url(state="s", nonce="n", verifier="v")).query)
    assert "ui_locales" not in without
    client.close()


def test_logout_page_follows_language(gateway, monkeypatch):
    client, cfg, _idp = gateway
    app = client.app
    from gateway.sessions import Session  # noqa: F401  (Name für die Lesbarkeit der Fixture)

    store = app.state.sessions if hasattr(app.state, "sessions") else None
    if store is None:
        pytest.skip("Sessions nicht über app.state erreichbar")
    session = store.create(sub="s", name="n", roles=("student",), id_token=None)
    client.cookies.set(cfg.cookie_name, session.sid)
    de = client.get("/logout").text
    assert '<html lang="de">' in de and "Sitzung beenden" in de
    en = client.get("/logout", headers={"Accept-Language": "en"}).text
    assert '<html lang="en">' in en and "End session" in en and "Sitzung" not in en


def test_realm_and_theme_have_both_languages():
    realm = json.loads((ROOT / "keycloak" / "hka-realm.json").read_text(encoding="utf-8"))
    assert realm["supportedLocales"] == list(LANGUAGES) and realm["defaultLocale"] == DEFAULT_LANGUAGE
    assert "locales=" + ",".join(LANGUAGES) in (THEME / "theme.properties").read_text(encoding="utf-8")


def keys(path):
    return {line.split("=", 1)[0] for line in path.read_text(encoding="utf-8").splitlines() if "=" in line}


def test_theme_texts_have_same_keys():
    de, en = keys(THEME / "messages" / "messages_de.properties"), keys(THEME / "messages" / "messages_en.properties")
    assert de == en and len(de) > 10
