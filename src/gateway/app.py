"""Standalone phase-1 gateway. Sync handlers deliberately run in FastAPI's threadpool.

The extracted OIDC client and redis-py store are synchronous; none runs directly
in the event loop. Access logs omit query strings, credentials and assertions.
"""

from contextlib import asynccontextmanager
import html
import json
import logging
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from redis import Redis
from redis.exceptions import RedisError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from .assertions import Assertions, verify_portal_context
from .config import Settings
from .oidc import OidcClient, OidcError
from .redis_sessions import RedisLoginStore, RedisSessionStore
from .sessions import Session
from .roles import RoleMapper, load_role_mapper
from .login_service import LoginService
from .exceptions import LoginFailedError, LoginRequiredError, NotFoundError, ForbiddenError, UnavailableError
from .registry_client import RegistryClient, RegistryUnavailableError
from .redirects import login_url
from .proxy import AppProxy, is_same_origin
from .config import AppsConfig
from .assertion_keys import InvalidAssertion
from .adapter_link import ROUTES as LINK_ROUTES, AdapterLink, AdapterUnavailable

log = logging.getLogger("gateway.access")


def valid_id(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is not None


def create_app(settings: Settings, *, redis_client=None, oidc_client=None, clock=time.time, role_mapper=None, registry_client=None, app_transport=None, portal_transport=None, adapter_transport=None):
    redis = redis_client if redis_client is not None else Redis.from_url(
        settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
    )
    oidc = oidc_client if oidc_client is not None else OidcClient(settings.oidc)
    sessions = RedisSessionStore(redis, idle_seconds=settings.idle_seconds,
                                 absolute_seconds=settings.session_seconds,
                                 touch_min_interval_seconds=settings.touch_min_interval_seconds, clock=clock)
    login_store = RedisLoginStore(redis, ttl_seconds=settings.login_seconds)
    role_mapper = role_mapper if role_mapper is not None else (
        load_role_mapper(settings.roles_file, settings.grants_file) if settings.roles_file else RoleMapper(())
    )
    login_service = LoginService(oidc, login_store, role_mapper, sessions)
    issuer = settings.assertion_issuer or settings.public_url + "/"
    assertions = Assertions(settings.signing_key, issuer, settings.portal_audience,
                            settings.assertion_seconds, clock, role_vocabulary=settings.role_vocabulary,
                            next_key=settings.signing_key_next, previous_key=settings.signing_key_previous)

    registry = registry_client
    if registry is None and settings.registry_url:
        registry = RegistryClient(settings.registry_url, settings.registry_token_file)
    portal_proxy = AppProxy(AppsConfig(settings.portal_upstream), portal_transport) if settings.portal_upstream else None

    proxy = AppProxy(settings.apps, app_transport) if settings.apps is not None else None
    adapter_link = AdapterLink(settings.adapter_url, adapter_transport) if settings.adapter_url else None

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if proxy is not None:
            await proxy.aclose()
        if portal_proxy is not None:
            await portal_proxy.aclose()
        if adapter_link is not None:
            await adapter_link.aclose()
        if registry is not None and registry_client is None:
            registry.close()
        if oidc_client is None:
            oidc.close()
        if redis_client is None:
            redis.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.sessions = sessions
    app.state.login_store = login_store
    app.state.assertions = assertions
    app.state.registry = registry
    app.state.portal_proxy = portal_proxy
    app.state.proxy = proxy
    app.state.adapter_link = adapter_link
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.public_url).hostname, *settings.internal_hosts])

    @app.middleware("http")
    async def headers_and_log(request, call_next):
        request.state.request_id = secrets.token_hex(16)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        # no-referrer makes browsers send Origin: null for this form's POST.
        response.headers["Referrer-Policy"] = (
            "same-origin" if request.method == "GET" and request.url.path == "/logout" else "no-referrer"
        )
        response.headers.setdefault("Cache-Control", "no-store")
        if getattr(request.state, "portal_forwarded", False) or getattr(request.state, "app_forwarded", False):
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers.setdefault("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        else:
            response.headers["Content-Security-Policy"] = "default-src 'none'; form-action 'self'; frame-ancestors 'none'"
        log.info(json.dumps({"event": "request", "request_id": request.state.request_id,
                             "method": request.method, "path": request.url.path, "status": response.status_code}))
        return response

    def problem(request, status, title):
        return JSONResponse({"type": f"urn:hka:gateway:{status}", "title": title, "status": status,
                             "request_id": getattr(request.state, "request_id", None)},
                            status_code=status, media_type="application/problem+json",
                            headers={"Cache-Control": "no-store"})

    def service_error(status, title):
        async def handler(request, _exc):
            return problem(request, status, title)
        return handler

    for error, status, title in ((NotFoundError, 404, "App not found"),
                                 (ForbiddenError, 403, "App access denied"),
                                 (UnavailableError, 503, "App unavailable")):
        app.add_exception_handler(error, service_error(status, title))

    @app.exception_handler(RegistryUnavailableError)
    async def registry_error(request, _exc):
        return problem(request, 503, "Registry unavailable")

    @app.exception_handler(RedisError)
    async def redis_error(request, _exc):
        return problem(request, 503, "Session storage unavailable")

    @app.exception_handler(LoginFailedError)
    async def login_error(request, _exc):
        return problem(request, 400, "Login failed")

    @app.exception_handler(LoginRequiredError)
    async def login_required(request, _exc):
        return RedirectResponse(login_url(request.url.path), status_code=302)

    @app.exception_handler(OidcError)
    async def oidc_error(request, _exc):
        return problem(request, 503, "Identity provider unavailable")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        response = problem(request, exc.status_code, str(exc.detail))
        response.headers.update(exc.headers or {})
        if request.url.path == "/oidc/callback":
            response.delete_cookie(settings.login_cookie, path="/", secure=settings.cookie_secure,
                                   httponly=True, samesite="lax")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, _exc):
        return problem(request, 422, "Invalid request")

    @app.exception_handler(Exception)
    async def unexpected_error(request, _exc):
        # No exception repr/trace: remote responses can contain credentials.
        return problem(request, 500, "Internal gateway error")

    def session_of(request) -> Session:
        sid = request.cookies.get(settings.cookie_name)
        # Preserve gateway SID validation around the unmodified portal store contract.
        if sid is not None and not valid_id(sid):
            raise HTTPException(401, "Login required")
        value = sessions.get(sid)
        if value is None:
            raise HTTPException(401, "Login required")
        return value

    def set_cookie(response, name, value, *, max_age=None):
        response.set_cookie(name, value, max_age=max_age, path="/", httponly=True,
                            secure=settings.cookie_secure, samesite="lax")

    @app.get("/apps/{slug}")
    def app_trailing_slash(slug: str):
        return RedirectResponse(f"/apps/{slug}/", status_code=308)

    @app.api_route("/apps/{slug}/{path:path}",
                   methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   include_in_schema=False)
    async def forward_to_app(request: Request, slug: str, path: str):
        if registry is None or proxy is None:
            raise HTTPException(503, "App routing is not configured")

        def authorize():
            # Synchronous Redis + registry HTTP calls must stay off the event loop.
            sid = request.cookies.get(settings.cookie_name)
            session = sessions.get(sid) if sid and valid_id(sid) else None
            if session is None:
                raise LoginRequiredError
            return session, registry.authorize(slug, assertions.mint(session))

        session, descriptor = await run_in_threadpool(authorize)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not is_same_origin(request):
            raise ForbiddenError(slug)
        assertion = await run_in_threadpool(assertions.mint_app, session, descriptor)
        request.state.app_forwarded = True
        return await proxy.forward(request, slug, assertion)

    # Konten verknüpfen (Portal-Seite "Verbindungen"): GET Status, POST start/poll, DELETE trennen.
    # JSON-API für fetch() der Portal-Seite: ohne Session 401 statt Weiterleitung zum Login.
    async def connect_bwsync(request: Request, sub_path: str):
        if adapter_link is None:
            raise HTTPException(503, "Account linking is not configured")
        sid = request.cookies.get(settings.cookie_name)
        session = await run_in_threadpool(sessions.get, sid) if sid and valid_id(sid) else None
        if session is None:
            raise HTTPException(401, "Login required")
        if request.method != "GET":
            # Wie bei Portal-Formularen: nur von der eigenen Seite (fetch sendet Origin immer).
            if (request.headers.get("origin") != settings.public_url or
                    request.headers.get("sec-fetch-site") in ("cross-site", "same-site")):
                raise HTTPException(403, "Foreign origin")
        assertion = await run_in_threadpool(assertions.mint_link, session)
        try:
            status, body = await adapter_link.call(request.method, sub_path, assertion, request.state.request_id)
        except AdapterUnavailable:
            raise HTTPException(503, "Account linking unavailable") from None
        return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})

    @app.api_route("/connect/bwsync", methods=["GET", "DELETE"], include_in_schema=False)
    async def connect_bwsync_root(request: Request):
        return await connect_bwsync(request, "")

    @app.post("/connect/bwsync/{step}", include_in_schema=False)
    async def connect_bwsync_step(request: Request, step: str):
        if ("POST", "/" + step) not in LINK_ROUTES:
            raise HTTPException(404, "Not found")
        return await connect_bwsync(request, "/" + step)

    @app.api_route("/connect/{rest:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   include_in_schema=False)
    def connect_unknown(rest: str):
        # /connect gehört dem Gateway; Unbekanntes nicht ans Portal weiterreichen.
        raise HTTPException(404, "Not found")

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        if not sessions.ping():
            raise HTTPException(503, "Session storage unavailable")
        return {"status": "ok", "checks": {"redis": "ok", "signing_key": "loaded"}}

    @app.get("/")
    async def home(request: Request):
        if portal_proxy is not None:
            return await forward_portal(request)
        sid = request.cookies.get(settings.cookie_name)
        session = await run_in_threadpool(sessions.get, sid) if sid and valid_id(sid) else None
        if session is None:
            # Use the same OIDC transaction and cookie handling as explicit login.
            return await run_in_threadpool(login, next="/")
        if settings.demo_enabled:
            return RedirectResponse("/demo", status_code=302)
        # Forwarding is opt-in. Without an upstream or demo, fail closed rather
        # than guessing a portal address or starting another login flow.
        raise HTTPException(503, "Portal integration is not configured")

    @app.get("/login")
    def login(next: str | None = None):
        started = login_service.start(next)
        response = RedirectResponse(started.url, status_code=302)
        set_cookie(response, settings.login_cookie, started.lid, max_age=settings.login_seconds)
        return response

    @app.get("/oidc/callback")
    def callback(request: Request, state: str | None = None, code: str | None = None, error: str | None = None):
        finished = login_service.finish(
            lid=request.cookies.get(settings.login_cookie), code=code, state=state,
            idp_error=error, old_sid=request.cookies.get(settings.cookie_name),
        )
        response = RedirectResponse(finished.next, status_code=302)
        set_cookie(response, settings.cookie_name, finished.session.sid)
        response.delete_cookie(settings.login_cookie, path="/", secure=settings.cookie_secure,
                               httponly=True, samesite="lax")
        return response

    @app.get("/me")
    def me(request: Request):
        session = session_of(request)
        return {"sub": session.sub, "name": session.name, "roles": sorted(session.roles),
                "expires_at": session.expires_at}

    @app.get("/.well-known/jwks.json")
    def jwks():
        return JSONResponse(assertions.jwks(), headers={"Cache-Control": "public, max-age=300"})

    if settings.demo_enabled:
        @app.get("/demo")
        def demo(request: Request):
            session = session_of(request)
            # Incoming browser identity headers are intentionally never consulted.
            token = assertions.mint(session)
            claims = verify_portal_context(token, assertions.jwks(), issuer, settings.portal_audience)
            return {"signature_verified": True, "user": {k: claims[k] for k in ("sub", "name", "roles")},
                    "assertion": {k: claims[k] for k in ("iss", "aud", "iat", "exp", "v", "token_use")}}

    @app.get("/logout")
    def logout_confirmation(request: Request):
        sid = request.cookies.get(settings.cookie_name)
        session = sessions.get(sid) if sid and valid_id(sid) else None
        if session is None:
            return RedirectResponse("/", status_code=302)
        csrf = html.escape(session.csrf, quote=True)
        return HTMLResponse(f'<h1>Abmelden</h1><form method="post" action="/logout">'
                            f'<input type="hidden" name="csrf" value="{csrf}">'
                            '<button type="submit">Sitzung beenden</button></form>')

    @app.post("/logout")
    def logout(request: Request, csrf: str = Form("")):
        sid = request.cookies.get(settings.cookie_name)
        session = sessions.get(sid) if sid and valid_id(sid) else None
        if session is None:
            raise HTTPException(400, "Login required")
        origin = request.headers.get("origin")
        if origin is not None and origin != settings.public_url:
            raise HTTPException(403, "Foreign origin")
        if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
            raise HTTPException(403, "Foreign origin")
        if not csrf:
            # Abmelden-Dialog im Seitenrahmen der Apps (SDK): ohne Token, dafür beide Browsersignale der eigenen
            # Herkunft. Fehlt eines (alter Browser, curl), kommt die Bestätigungsseite mit Token statt eines Fehlers.
            if origin != settings.public_url or request.headers.get("sec-fetch-site") != "same-origin":
                return RedirectResponse("/logout", status_code=303)
        elif not session.csrf_matches(csrf):
            raise HTTPException(400, "Invalid CSRF token")
        sessions.delete(session.sid)
        # End the local session even if IdP discovery fails during logout.
        url = oidc.end_session_url(session.id_token)
        response = RedirectResponse(url or "/", status_code=303)
        response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure,
                               httponly=True, samesite="lax")
        return response


    async def forward_portal(request: Request):
        path = request.url.path
        if path == "/demo" and not settings.demo_enabled:
            raise HTTPException(404, "Not found")
        if path in ("/me", "/healthz", "/readyz", "/.well-known/jwks.json", "/demo"):
            raise HTTPException(405, "Method not allowed", headers={"Allow": "GET"})
        if path in ("/login", "/logout", "/oidc/callback"):
            raise HTTPException(405, "Method not allowed")
        if path == "/internal" or path.startswith("/internal/"):
            raise HTTPException(404, "Not found")
        if portal_proxy is None:
            raise HTTPException(503, "Portal integration is not configured")
        # SDK navigation is a server-to-server app-token contract, never a UI login.
        if path == "/nav" and request.headers.get("authorization", "").startswith("Bearer "):
            token = request.headers["authorization"][7:]
            try:
                claims = assertions.keys.verify(token, "portal")
                if claims.get("token_use") is not None or not claims.get("azp"):
                    raise InvalidAssertion("Wrong purpose")
            except InvalidAssertion:
                raise HTTPException(401, "Invalid navigation assertion") from None
            request.state.portal_forwarded = True
            return await portal_proxy.forward(request, "portal", token, navigation_token=token)
        sid = request.cookies.get(settings.cookie_name)
        session = await run_in_threadpool(sessions.get, sid) if sid and valid_id(sid) else None
        if session is None:
            if request.method not in ("GET", "HEAD"):
                raise HTTPException(401, "Login required")
            return await run_in_threadpool(login, next=path)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if (request.headers.get("origin") != settings.public_url or
                    request.headers.get("sec-fetch-site") in ("cross-site", "same-site")):
                raise HTTPException(403, "Foreign origin")
        token = await run_in_threadpool(assertions.mint, session)
        request.state.portal_forwarded = True
        return await portal_proxy.forward(request, "portal", token)

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def portal_route(request: Request, path: str):
        return await forward_portal(request)

    return app
