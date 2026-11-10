#!/usr/bin/env python3
"""Real Keycloak browser-form smoke test (stdlib, no password grant).

Uses existing Keycloak with a dedicated cookie jar. Does not stop services.
Optionally wait for expiry after starting with GW_SESSION_SECONDS=5.
"""
import argparse
import http.cookiejar
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


class Forms(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms, self.current = [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"action": attrs.get("action"), "fields": {}}
            self.forms.append(self.current)
        elif tag == "input" and self.current is not None and attrs.get("name"):
            self.current["fields"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-expiry", type=int, default=0, help="Seconds to wait; must exceed configured session TTL")
    args = parser.parse_args()
    base = os.environ.get("GW_PUBLIC_URL", "http://localhost:18080").rstrip("/")
    username = os.environ.get("GW_TEST_USERNAME")
    password_file = os.environ.get("GW_TEST_PASSWORD_FILE")
    if not username or not password_file:
        parser.error("Set GW_TEST_USERNAME and GW_TEST_PASSWORD_FILE for an existing approved test account")
    password = Path(password_file).read_text().strip()
    issuer = urlsplit(os.environ.get("GW_OIDC_ISSUER", "http://localhost:8180/realms/hka"))
    idp_origin = f"{issuer.scheme}://{issuer.netloc}/"
    jar = http.cookiejar.CookieJar()
    browser = build_opener(HTTPCookieProcessor(jar))

    def get(path, *, data=None):
        request = Request(path if path.startswith("http") else base + path,
                          data=urlencode(data).encode() if data is not None else None)
        try:
            with browser.open(request, timeout=15) as response:
                return response.status, response.read().decode()
        except HTTPError as exc:
            return exc.code, exc.read().decode()

    assert get("/readyz")[0] == 200, "Gateway/Redis not ready"
    assert get("/me")[0] == 401, "Anonymous request accepted"
    status, page = get("/login")
    assert status == 200, "Keycloak login not reachable (wait for startup)"
    forms = Forms()
    forms.feed(page)
    form = next(form for form in forms.forms if "password" in form["fields"])
    assert form["action"].startswith(idp_origin), "Unexpected IdP origin"
    fields = {**form["fields"], "username": username, "password": password}
    status, body = get(form["action"], data=fields)
    assert status == 200, "OIDC login failed"
    result = json.loads(get("/demo")[1])
    assert result["signature_verified"] is True, "Portal mock rejected assertion"
    assert result["assertion"]["aud"] == "hka-portal-ui"
    assert result["assertion"]["token_use"] == "portal-ui"
    assert get("/me")[0] == 200
    cookie_name = "__Host-hka_gateway_sid" if base.startswith("https://") else "hka_gateway_sid"
    saved = next(cookie.value for cookie in jar if cookie.name == cookie_name)
    assert len(saved) == 43
    jwks = json.loads(get("/.well-known/jwks.json")[1])
    assert jwks["keys"][0]["alg"] == "RS256" and "d" not in jwks["keys"][0]
    print("PASS: real Keycloak Code + PKCE login, Redis-backed access, verified assertion, public JWKS")
    status, page = get("/logout")
    assert status == 200
    forms = Forms()
    forms.feed(page)
    csrf = next(form["fields"]["csrf"] for form in forms.forms if "csrf" in form["fields"])
    get("/logout", data={"csrf": csrf})
    assert get("/me")[0] == 401, "Logout did not revoke access"
    # Replay the pre-logout cookie, not merely the now-empty browser cookie jar.
    replay = Request(base + "/me", headers={"Cookie": cookie_name + "=" + saved})
    try:
        browser.open(replay, timeout=5)
        raise AssertionError("Old session cookie still accepted")
    except HTTPError as exc:
        assert exc.code == 401
    print("PASS: CSRF-protected logout and replay of invalidated cookie denied")
    if args.wait_expiry:
        jar.clear()
        status, page = get("/login")
        forms = Forms()
        forms.feed(page)
        # SSO may directly return the demo, otherwise submit the login form again.
        try:
            assert json.loads(get("/demo")[1])["signature_verified"]
        except (ValueError, KeyError):
            form = next(form for form in forms.forms if "password" in form["fields"])
            assert form["action"].startswith(idp_origin), "Unexpected IdP origin"
            status, _ = get(form["action"], data={**form["fields"], "username": username, "password": password})
            assert status == 200
        time.sleep(args.wait_expiry)
        assert get("/me")[0] == 401
        print("PASS: configured session expiry")


if __name__ == "__main__":
    main()
