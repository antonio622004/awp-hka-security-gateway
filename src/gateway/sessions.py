"""Session model/protocol extracted from portal/auth/sessions.py (b7823bb).

No MemorySessionStore is included. expires_at is gateway response metadata;
it is computed from created + absolute_seconds, not a separate Redis field.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Session:
    """Eine angemeldete Session.

    :ivar sid: Session-ID (Wert des Cookies)
    :ivar sub: Subject des IdP
    :ivar name: Anzeigename
    :ivar roles: Rollen
    :ivar csrf: CSRF-Token für Formulare
    :ivar id_token: ID-Token des IdP, nur als ``id_token_hint`` für die Abmeldung beim IdP
    """
    sid: str
    sub: str
    name: str
    roles: frozenset[str]
    csrf: str
    id_token: str | None = None
    expires_at: int = 0

    def has_role(self, role: str) -> bool:
        """Ob die Session eine Rolle hat.

        :param role: Gesuchte Rolle
        :return: ``True``, falls vorhanden
        :rtype: bool
        """
        return role in self.roles

    def csrf_matches(self, token: str) -> bool:
        """Ob das Token zum CSRF-Token der Session passt (zeitkonstanter Vergleich).

        :param token: Token aus dem Formular
        :return: ``True`` bei Übereinstimmung
        :rtype: bool
        """
        return secrets.compare_digest(token, self.csrf)


class SessionStore(Protocol):
    """Übernommener Store-Vertrag; der Gateway verwendet ausschließlich Redis."""

    def create(self, sub: str, name: str, roles: frozenset[str], id_token: str | None = None) -> Session:
        """Eine Session anlegen.

        :param sub: Subject des IdP
        :param name: Anzeigename
        :param roles: Rollen
        :param id_token: ID-Token des IdP für die Abmeldung beim IdP
        :return: Die neue Session
        :rtype: Session
        """
        ...

    def get(self, sid: str | None) -> Session | None:
        """Eine Session suchen.

        :param sid: Session-ID, ``None`` oder leer ergibt ``None``
        :return: Die Session oder ``None``
        :rtype: Session | None
        """
        ...

    def delete(self, sid: str) -> None:
        """Eine Session löschen; eine unbekannte ID wird ignoriert.

        :param sid: Session-ID
        """
        ...

    def ping(self) -> bool:
        """Ob der Store erreichbar ist.

        :return: ``True``, falls erreichbar
        :rtype: bool
        """
        ...
