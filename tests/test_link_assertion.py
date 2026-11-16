"""Assertion zum Verknüpfen von Konten: nur das Gateway stellt sie aus, Apps bekommen den Scope nie."""
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

from gateway.assertion_keys import InvalidAssertion
from gateway.assertions import Assertions
from gateway.sessions import Session

ISSUER = "https://gateway.test/"


@pytest.fixture
def assertions(tmp_path):
    path = tmp_path / "key.pem"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return Assertions(path, ISSUER, "hka-portal-ui", role_vocabulary=("student",))


USER = Session("sid", "subject-1", "Name", frozenset({"student"}), "csrf")


def verify_like_adapter(assertions, token):
    """Signatur über die veröffentlichten JWKS prüfen, wie es der Adapter tut."""
    kid = jwt.get_unverified_header(token)["kid"]
    key = jwt.PyJWKSet.from_dict(assertions.jwks())[kid].key
    return jwt.decode(token, key, algorithms=["RS256"], audience="adapters", issuer=ISSUER)


def test_link_assertion_claims_fit_the_adapter(assertions):
    token = assertions.mint_link(USER)
    claims = verify_like_adapter(assertions, token)
    # Genau das, was der Adapter für /bwsync/link verlangt: aud "adapters", azp "portal" (und in aud), v 1.
    assert claims["iss"] == ISSUER and claims["sub"] == "subject-1"
    assert claims["aud"] == ["adapters", "portal"] and claims["azp"] == "portal"
    assert claims["scp"] == ["bwsync:link"] and claims["v"] == 1
    assert claims["exp"] - claims["iat"] == 60
    # Keine Personendaten, die der Adapter nicht braucht; kein portal-ui-Zweck (sonst passt es zur Portal-UI).
    assert not {"name", "roles", "csrf", "token_use"} & set(claims)
    # Ohne roles lehnt die /nav-Prüfung des Gateways das Token ab: es taugt nur für den Adapter.
    with pytest.raises(InvalidAssertion):
        assertions.keys.verify(token, "portal")


def test_link_assertion_only_for_link_scopes(assertions):
    for scope in ("bwsync:read", "bwsync:write", "noten:read", ""):
        with pytest.raises(ValueError):
            assertions.mint_link(USER, scope)


@pytest.mark.parametrize("scopes,expected_scp,adapters_audience", [
    (("bwsync:link",), [], False),
    (("bwsync:read", "bwsync:link", "bwsync:write"), ["bwsync:read", "bwsync:write"], True),
    (("bwsync:read",), ["bwsync:read"], True),
])
def test_app_assertions_never_carry_link_scope(assertions, scopes, expected_scp, adapters_audience):
    # Auch wenn die Registry den Scope je lieferte: Apps bekommen ihn nie.
    token = assertions.mint_app(USER, SimpleNamespace(slug="syncshare", adapters=scopes))
    claims = assertions.keys.verify(token, "syncshare")
    assert claims["scp"] == expected_scp
    assert ("adapters" in claims["aud"]) is adapters_audience
    assert claims["azp"] == "syncshare"


@pytest.mark.parametrize("slug", ["portal", "adapters"])
def test_no_app_can_be_named_like_the_link_party(assertions, slug):
    with pytest.raises(ValueError):
        assertions.mint(USER, purpose="micro-app", app_slug=slug)
