"""Konten verknüpfen: das Gateway reicht genau vier Aufrufe aus dem Browser an den Adapter weiter.

Aufrufer ist das Skript einer App-Seite (SyncShare: „bwSync&Share verbinden“/„Konto trennen“) per fetch().

Der Browser spricht nur mit dem Gateway (/connect/bwsync…). Das Gateway prüft Session und Herkunft, stellt eine
Link-Assertion aus und ruft den Adapter auf. Zurück geht nur ein festgelegter Satz an Feldern; nichts aus dem
Browser (Cookies, Header, Body) wird weitergegeben.
"""

from __future__ import annotations

from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any, Final

import httpx

# (Methode, Pfad unter /connect/bwsync) -> (Pfad beim Adapter, erlaubte Felder der Antwort)
ROUTES: Final = {
    ("GET", ""): ("/bwsync/link", ("linked", "account")),
    ("POST", "/start"): ("/bwsync/link/start", ("login_url", "expires_in")),
    ("POST", "/poll"): ("/bwsync/link/poll", ("state", "account")),
    ("DELETE", ""): ("/bwsync/link", ("linked", "revoked")),
}
ERROR_FIELDS: Final = ("type", "detail")


class AdapterUnavailable(Exception):
    """Adapter nicht erreichbar oder Antwort unbrauchbar."""


class AdapterLink:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base = base_url.rstrip("/")
        # Länger als der Adapter (15 s zu bwSync), damit dessen Fehlermeldung ankommt.
        # Ein Client für alle Personen: nie Cookies speichern oder mitschicken (Jar direkt übergeben, nicht
        # httpx.Cookies, das in ein Jar ohne diese Regel kopieren würde).
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=3.0), follow_redirects=False,
                                        trust_env=False, transport=transport,
                                        cookies=CookieJar(policy=DefaultCookiePolicy(allowed_domains=[])))

    async def aclose(self) -> None:
        await self.client.aclose()

    async def call(self, method: str, sub_path: str, assertion: str, request_id: str) -> tuple[int, dict[str, Any]]:
        adapter_path, fields = ROUTES[(method, sub_path)]
        try:
            response = await self.client.request(
                method, self._base + adapter_path,
                headers={"Authorization": f"Bearer {assertion}", "X-Request-Id": request_id,
                         "Accept": "application/json"})
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise AdapterUnavailable from None
        if not isinstance(body, dict):
            raise AdapterUnavailable
        allowed = fields if response.is_success else ERROR_FIELDS
        if not response.is_success and not (400 <= response.status_code < 600):
            raise AdapterUnavailable
        result = {k: body[k] for k in allowed if k in body}
        # Der Browser öffnet login_url: nur https, nie javascript: o. Ä.
        if "login_url" in result and not (isinstance(result["login_url"], str)
                                          and result["login_url"].startswith("https://")):
            raise AdapterUnavailable
        return response.status_code, result
