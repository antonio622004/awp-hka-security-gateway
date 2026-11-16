"""/connect/bwsync…: Session nötig, nur eigene Herkunft, Link-Assertion zum Adapter, gefilterte Antwort."""
from dataclasses import replace

from fastapi.testclient import TestClient
import httpx
import jwt
import pytest

from gateway.app import create_app
from gateway.config import ConfigError
from test_app import env, login  # noqa: F401  (Fixture und Anmeldung wiederverwenden)

ADAPTER = "http://adapter:8080"


@pytest.fixture
def linked(env):  # noqa: F811
    source_client, _source_app, cfg, redis, _state, now = env
    login(env)
    sid = source_client.cookies[cfg.cookie_name]
    cfg = replace(cfg, adapter_url=ADAPTER)
    calls = []
    answers = {
        ("GET", "/bwsync/link"): (200, {"linked": True, "account": "id@idp.test", "extra": "drop-me"}),
        ("POST", "/bwsync/link/start"): (200, {"login_url": "https://dav.test/login/v2/flow/x", "expires_in": 1200,
                                               "token": "never-to-browser"}),
        ("POST", "/bwsync/link/poll"): (200, {"state": "linked", "account": "id@idp.test",
                                              "appPassword": "never-to-browser"}),
        ("DELETE", "/bwsync/link"): (200, {"linked": False, "revoked": True}),
    }

    def adapter(request):
        calls.append(request)
        status, body = answers[(request.method, request.url.path)]
        return httpx.Response(status, json=body)

    class UnusedOidc:
        pass
    app = create_app(cfg, redis_client=redis, oidc_client=UnusedOidc(), adapter_transport=httpx.MockTransport(adapter),
                     clock=lambda: now[0])
    with TestClient(app, base_url=cfg.public_url, follow_redirects=False) as client:
        client.cookies.set(cfg.cookie_name, sid)
        yield client, app, cfg, calls, answers
    assert app.state.adapter_link.client.is_closed


def same_origin(cfg):
    return {"Origin": cfg.public_url, "Sec-Fetch-Site": "same-origin"}


def adapter_claims(app, request):
    token = request.headers["authorization"].removeprefix("Bearer ")
    key = jwt.PyJWKSet.from_dict(app.state.assertions.jwks())[jwt.get_unverified_header(token)["kid"]].key
    return jwt.decode(token, key, algorithms=["RS256"], audience="adapters")


@pytest.mark.parametrize("method,path,adapter_path,expected", [
    ("GET", "/connect/bwsync", "/bwsync/link", {"linked": True, "account": "id@idp.test"}),
    ("POST", "/connect/bwsync/start", "/bwsync/link/start",
     {"login_url": "https://dav.test/login/v2/flow/x", "expires_in": 1200}),
    ("POST", "/connect/bwsync/poll", "/bwsync/link/poll", {"state": "linked", "account": "id@idp.test"}),
    ("DELETE", "/connect/bwsync", "/bwsync/link", {"linked": False, "revoked": True}),
])
def test_forwards_with_link_assertion_and_filters_answer(linked, method, path, adapter_path, expected):
    client, app, cfg, calls, _answers = linked
    response = client.request(method, path, headers={**same_origin(cfg), "Authorization": "Bearer browser-token",
                                                     "X-Portal-Assertion": "forged"})
    assert response.status_code == 200 and response.json() == expected
    assert response.headers["cache-control"] == "no-store"
    assert "never-to-browser" not in response.text
    assert len(calls) == 1 and calls[0].method == method and str(calls[0].url) == ADAPTER + adapter_path
    request = calls[0]
    # Nichts aus dem Browser beim Adapter: keine Cookies, kein Browser-Token, kein Body
    assert "cookie" not in request.headers and "x-portal-assertion" not in request.headers
    assert request.content == b""
    claims = adapter_claims(app, request)
    assert claims["sub"] == "subject-1" and claims["azp"] == "portal" and claims["scp"] == ["bwsync:link"]
    assert request.headers["x-request-id"] == response.headers["x-request-id"]


@pytest.mark.parametrize("method,path", [("GET", "/connect/bwsync"), ("POST", "/connect/bwsync/start"),
                                         ("POST", "/connect/bwsync/poll"), ("DELETE", "/connect/bwsync")])
def test_without_session_is_401_not_a_login_redirect(linked, method, path):
    client, _app, cfg, calls, _answers = linked
    client.cookies.clear()
    response = client.request(method, path, headers=same_origin(cfg))
    assert response.status_code == 401 and "location" not in response.headers
    assert calls == []


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://evil.test"}, {"Origin": "null"},
                                     {"Origin": "http://localhost:18080", "Sec-Fetch-Site": "cross-site"},
                                     {"Origin": "http://localhost:18080", "Sec-Fetch-Site": "same-site"}])
@pytest.mark.parametrize("method,path", [("POST", "/connect/bwsync/start"), ("POST", "/connect/bwsync/poll"),
                                         ("DELETE", "/connect/bwsync")])
def test_side_effects_only_from_own_origin(linked, headers, method, path):
    client, _app, _cfg, calls, _answers = linked
    response = client.request(method, path, headers=headers)
    assert response.status_code == 403
    assert calls == []


def test_unknown_step_and_methods(linked):
    client, _app, cfg, calls, _answers = linked
    assert client.post("/connect/bwsync/other", headers=same_origin(cfg)).status_code == 404
    assert client.get("/connect/bwsync/start").status_code == 404
    assert client.put("/connect/bwsync", headers=same_origin(cfg)).status_code == 404
    assert client.get("/connect/other").status_code == 404
    assert calls == []


def test_adapter_errors_pass_only_type_and_detail(linked):
    client, _app, cfg, _calls, answers = linked
    answers[("POST", "/bwsync/link/start")] = (502, {"type": "urn:hka:problem:x", "detail": "Nicht erreichbar",
                                                     "trace": "private"})
    response = client.post("/connect/bwsync/start", headers=same_origin(cfg))
    assert response.status_code == 502
    assert response.json() == {"type": "urn:hka:problem:x", "detail": "Nicht erreichbar"}


@pytest.mark.parametrize("login_url", ["javascript:alert(1)", "http://dav.test/x", 42])
def test_non_https_login_url_never_reaches_browser(linked, login_url):
    client, _app, cfg, _calls, answers = linked
    answers[("POST", "/bwsync/link/start")] = (200, {"login_url": login_url, "expires_in": 1200})
    response = client.post("/connect/bwsync/start", headers=same_origin(cfg))
    assert response.status_code == 503 and "alert" not in response.text


def test_adapter_unreachable_is_503(env):  # noqa: F811
    source_client, _source_app, cfg, redis, _state, now = env
    login(env)
    sid = source_client.cookies[cfg.cookie_name]

    def down(request):
        raise httpx.ConnectError("private details", request=request)

    class UnusedOidc:
        pass
    app = create_app(replace(cfg, adapter_url=ADAPTER), redis_client=redis, oidc_client=UnusedOidc(),
                     adapter_transport=httpx.MockTransport(down), clock=lambda: now[0])
    with TestClient(app, base_url=cfg.public_url, follow_redirects=False) as client:
        client.cookies.set(cfg.cookie_name, sid)
        response = client.get("/connect/bwsync")
        assert response.status_code == 503 and "private" not in response.text


def test_without_adapter_url_linking_is_off(env):  # noqa: F811
    client, *_ = env
    login(env)
    assert client.get("/connect/bwsync").status_code == 503


@pytest.mark.parametrize("url", ["ftp://adapter", "http://user:pw@adapter:8080", "http://adapter:8080/path",
                                 "http://adapter:8080?x=1"])
def test_adapter_url_must_be_plain_origin(env, url):  # noqa: F811
    _client, _app, cfg, *_ = env
    with pytest.raises(ConfigError):
        replace(cfg, adapter_url=url)
