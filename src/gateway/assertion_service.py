"""AssertionService: Identitäts-Token für Apps ausstellen (02 §7)."""

from __future__ import annotations

import time
import uuid
from typing import Final, Protocol

import logging

from .assertion_keys import TOKEN_VERSION, SigningKeys
from .config import AssertionConfig
from .sessions import Session as SessionDTO

class AppDTO(Protocol):
    """Only assertion inputs; registry storage remains in the portal."""
    slug: str
    adapters: tuple[str, ...]


logger = logging.getLogger(__name__)
PORTAL_AUDIENCE: Final = "portal"
ADAPTERS_AUDIENCE: Final = "adapters"


class AssertionService:
    """Service-Klasse, die aus Session und App ein signiertes Token macht."""

    def __init__(self, keys: SigningKeys, cfg: AssertionConfig, role_vocabulary: tuple[str, ...]) -> None:
        """Konstruktor.

        :param keys: Schlüssel zum Signieren
        :param cfg: Einstellungen des Tokens
        :param role_vocabulary: Rollen, die ins Token dürfen
        """
        self.keys: Final = keys
        self.cfg: Final = cfg
        self.role_vocabulary: Final = frozenset(role_vocabulary)

    def mint(self, session: SessionDTO, app: AppDTO) -> str:
        """Token für eine Person und eine App.

        ``aud`` enthält den Slug und ``portal`` (für ``/nav``), bei Apps mit Adaptern auch ``adapters``.
        ``email`` fehlt, weil die Session keine E-Mail-Adresse speichert.

        :param session: Angemeldete Session
        :param app: App, die aufgerufen wird
        :return: Kompaktes JWT, gültig ``ttl_seconds``
        :rtype: str
        """
        logger.debug("slug=%s", app.slug)
        now: Final = int(time.time())
        audience: Final = [app.slug, PORTAL_AUDIENCE]
        if app.adapters:
            audience.append(ADAPTERS_AUDIENCE)
        return self.keys.sign(
            {
                "iss": self.cfg.issuer,
                "sub": session.sub,
                "name": session.name,
                "roles": sorted(session.roles & self.role_vocabulary),
                "aud": audience,
                "azp": app.slug,
                "scp": list(app.adapters),
                "iat": now,
                "exp": now + self.cfg.ttl_seconds,
                "jti": str(uuid.uuid4()),
                "v": TOKEN_VERSION,
            }
        )
