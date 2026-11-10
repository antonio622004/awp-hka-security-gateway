"""Uncached authorization-decision client; policy evaluation remains in the portal."""
from dataclasses import dataclass
from pathlib import Path
import json
import re

import httpx


class RegistryUnavailableError(Exception):
    """No trusted, valid policy is available: never fall back to previous data."""


@dataclass(frozen=True)
class AppAccess:
    slug: str
    adapters: tuple[str, ...]


class RegistryClient:
    def __init__(self, url: str, token_file: Path, *, transport=None):
        token = token_file.read_text(encoding="ascii").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token) is None:
            raise ValueError("Registry service token must be 43–128 base64url characters")
        self._token = token
        self._url = url.rstrip("/")
        self._http = httpx.Client(timeout=2.0, follow_redirects=False, trust_env=False, transport=transport)

    def authorize(self, slug: str, assertion: str) -> AppAccess:
        from .exceptions import ForbiddenError, NotFoundError, UnavailableError
        if re.fullmatch(r"[a-z][a-z0-9-]{2,30}", slug) is None:
            raise NotFoundError(slug)
        request = httpx.Request("POST", f"{self._url}/internal/apps/{slug}/authorize",
                                headers={"Authorization": "Bearer " + self._token,
                                         "X-Portal-Assertion": assertion, "Accept": "application/json"})
        try:
            response = self._http.send(request, stream=True)
            try:
                if response.headers.get("content-type", "").split(";")[0].lower() != "application/json":
                    raise RegistryUnavailableError("Invalid decision response")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise RegistryUnavailableError("Invalid decision response")
                data = json.loads(body)
                denied = {403: ("forbidden", ForbiddenError), 404: ("not_found", NotFoundError),
                          503: ("unavailable", UnavailableError)}
                if response.status_code in denied:
                    reason, error = denied[response.status_code]
                    if data == {"slug": slug, "allowed": False, "reason": reason}:
                        raise error(slug)
                if (response.status_code != 200 or not isinstance(data, dict)
                        or set(data) != {"slug", "allowed", "adapters"}
                        or data["slug"] != slug or data["allowed"] is not True):
                    raise RegistryUnavailableError("Invalid decision response")
                scopes = data["adapters"]
                if (not isinstance(scopes, list) or
                        not all(isinstance(v, str) and re.fullmatch(r"[a-z][a-z0-9-]*:[a-z][a-z0-9-]*", v) for v in scopes)
                        or len(set(scopes)) != len(scopes)):
                    raise RegistryUnavailableError("Invalid decision response")
                return AppAccess(slug, tuple(scopes))
            finally:
                response.close()
        except (httpx.HTTPError, ValueError, TypeError):
            raise RegistryUnavailableError("Portal authorization unavailable") from None

    def close(self):
        self._http.close()
