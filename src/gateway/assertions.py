"""RS256 / RFC7638 logic extracted from portal.auth.assertion_keys.

No token-mint endpoint: assertions are only created after session validation.
"""

import json
import re
import time
import uuid

import jwt
from jwt.algorithms import RSAAlgorithm

from types import SimpleNamespace

from .sessions import Session
from .config import AssertionConfig
from .assertion_keys import SigningKeys
from .assertion_service import AssertionService


class Assertions:
    """Gateway facade around the portal key implementation.

    Portal UI assertions retain their separate audience and purpose. App claims
    are produced by the extracted AssertionService, not a second claim builder.
    """
    def __init__(self, path, issuer, portal_audience, ttl=60, clock=time.time, *,
                 role_vocabulary=(), next_key=None, previous_key=None):
        cfg = AssertionConfig(issuer, ttl, path, next_key, previous_key)
        self.keys = SigningKeys.load(cfg, dev=False)
        if self.keys.current.private.key_size < 2048:
            raise ValueError("A private RSA key of at least 2048 bits is required")
        self.key = self.keys.current.private
        self.kid = self.keys.current.kid
        self.issuer, self.portal_audience, self.ttl, self.clock = issuer, portal_audience, ttl, clock
        self.apps = AssertionService(self.keys, cfg, role_vocabulary)

    def jwks(self):
        return self.keys.jwks()

    def mint_app(self, session, app):
        return self.apps.mint(session, app)

    def mint_link(self, session, scope="bwsync:link"):
        return self.apps.mint_link(session, scope)

    def mint(self, session: Session, *, purpose="portal-ui", app_slug=None):
        if purpose == "micro-app" and isinstance(app_slug, str) and re.fullmatch(r"[a-z][a-z0-9-]{2,30}", app_slug):
            if app_slug in (self.portal_audience, "portal", "adapters"):
                raise ValueError("Invalid assertion purpose/audience")
            return self.mint_app(session, SimpleNamespace(slug=app_slug, adapters=()))
        if purpose != "portal-ui" or app_slug is not None:
            raise ValueError("Invalid assertion purpose/audience")
        now = int(self.clock())
        return self.keys.sign(
            {"iss": self.issuer, "aud": self.portal_audience, "sub": session.sub, "name": session.name,
             "roles": sorted(session.roles), "iat": now, "exp": now + self.ttl, "jti": str(uuid.uuid4()),
             "v": 1, "token_use": purpose, "csrf": session.csrf},
        )


def verify_portal_context(token, jwks, issuer, audience):
    """Small mock receiver: public keys only; rejects app tokens even if signed here."""
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256":
        raise jwt.InvalidAlgorithmError("Only RS256 allowed")
    key = next((key for key in jwks["keys"] if key["kid"] == header.get("kid")), None)
    if key is None:
        raise jwt.InvalidTokenError("Unknown key")
    claims = jwt.decode(token, RSAAlgorithm.from_jwk(json.dumps(key)), algorithms=["RS256"],
                        issuer=issuer, audience=audience,
                        options={"require": ["iss", "aud", "sub", "iat", "exp", "v", "token_use", "roles"]})
    if claims["token_use"] != "portal-ui" or claims["v"] != 1:
        raise jwt.InvalidTokenError("Wrong token purpose/version")
    if not isinstance(claims["sub"], str) or not claims["sub"]:
        raise jwt.InvalidTokenError("Invalid subject")
    if not isinstance(claims["roles"], list) or not all(isinstance(r, str) for r in claims["roles"]):
        raise jwt.InvalidTokenError("Invalid roles")
    return claims
