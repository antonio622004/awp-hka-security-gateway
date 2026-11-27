"""Complete HTTP/OIDC flow with signed IdP tokens and fakeredis, no containers."""
from dataclasses import replace
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import fakeredis
from fastapi.testclient import TestClient
import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from gateway.app import create_app
from gateway.config import OidcConfig, Settings
from gateway.oidc import OidcClient, pkce_challenge
from gateway.redis_sessions import PREFIX, _user_key


@pytest.fixture
def env(tmp_path):
    now = [time.time()]
    idp_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_file = tmp_path / "gateway.pem"
    key_file.write_bytes(signing.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    roles_file = tmp_path / "roles.yml"
    roles_file.write_text("sources:\n  - claim: affiliation\n    map: {student: student}\ndefault_roles: []\n")
    cfg = Settings("http://localhost:18080",
                   OidcConfig("http://localhost:18180/realms/test", "gateway", "test-only",
                              "http://localhost:18080/oidc/callback", "http://localhost:18080/"),
                   key_file, cookie_secure=False, cookie_name="test_sid", login_cookie="test_login", demo_enabled=True,
                   roles_file=roles_file, role_vocabulary=("student",))
    state = {"nonce": "", "overrides": {}, "post_count": 0}

    def idp(request):
        issuer = cfg.oidc.issuer
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"issuer": issuer, "authorization_endpoint": issuer + "/auth",
                                            "token_endpoint": issuer + "/token", "jwks_uri": issuer + "/certs",
                                            "end_session_endpoint": issuer + "/logout"})
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [{**json.loads(RSAAlgorithm.to_jwk(idp_key.public_key())),
                                                       "kid": "idp"}]})
        assert request.url.path.endswith("/token")
        state["post_count"] += 1
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["code"]
        assert state["challenge"] == pkce_challenge(form["code_verifier"][0])
        claims = {"iss": issuer, "aud": "gateway", "sub": "subject-1", "name": "Gateway Demo",
                  "affiliation": "student", "nonce": state["nonce"], "iat": int(time.time()), "exp": int(time.time()) + 60,
                  **state["overrides"]}
        token = jwt.encode(claims, idp_key, algorithm="RS256", headers={"kid": "idp"})
        return httpx.Response(200, json={"id_token": token, "access_token": "must-not-leave-idp-client",
                                        "refresh_token": "must-not-be-stored"})

    redis = fakeredis.FakeRedis(decode_responses=True)
    oidc = OidcClient(cfg.oidc, httpx.Client(transport=httpx.MockTransport(idp)))
    app = create_app(cfg, redis_client=redis, oidc_client=oidc, clock=lambda: now[0])
    with TestClient(app, base_url=cfg.public_url, follow_redirects=False) as client:
        yield client, app, cfg, redis, state, now
    oidc.close()


def start(env, next_path=None):
    client, _app, cfg, _redis, state, _now = env
    response = client.get("/login", params={"next": next_path} if next_path is not None else {})
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    state["nonce"], state["challenge"] = query["nonce"][0], query["code_challenge"][0]
    assert "httponly" in response.headers["set-cookie"].lower()
    return query["state"][0]


def login(env):
    state = start(env)
    return env[0].get("/oidc/callback", params={"state": state, "code": "code"})


def test_login_redis_session_protected_demo_and_jwks(env):
    client, app, cfg, redis, _state, _now = env
    assert login(env).status_code == 302
    sid = client.cookies[cfg.cookie_name]
    stored = redis.hgetall(PREFIX + "sess:" + sid)
    assert stored["sub"] == "subject-1" and "refresh_token" not in stored
    assert redis.smembers(_user_key("subject-1")) == {sid}
    assert 0 < redis.ttl(PREFIX + "sess:" + sid) <= 300
    response = client.get("/demo", headers={"X-Portal-Assertion": "forged", "X-Gateway-Context": "forged"})
    assert response.status_code == 200 and response.json()["signature_verified"]
    assert response.json()["user"]["sub"] == "subject-1"
    assert "must-not" not in response.text and "id_token" not in response.text
    assert response.json()["assertion"]["exp"] - response.json()["assertion"]["iat"] == 60
    jwks = client.get("/.well-known/jwks.json").json()
    assert "d" not in jwks["keys"][0]
    token = app.state.assertions.mint(app.state.sessions.get(sid))
    key = RSAAlgorithm.from_jwk(json.dumps(jwks["keys"][0]))
    assert jwt.decode(token, key, algorithms=["RS256"], issuer=cfg.public_url + "/",
                      audience=cfg.portal_audience)["sub"] == "subject-1"


def test_no_session_expired_session_and_forged_header(env):
    client, _app, _cfg, _redis, _state, now = env
    assert client.get("/demo", headers={"X-Portal-Assertion": "forged"}).status_code == 401
    login(env)
    now[0] += 301
    assert client.get("/me").status_code == 401
    assert client.get("/demo").status_code == 401


def test_logout_csrf_and_invalidation(env):
    client, _app, cfg, redis, _state, _now = env
    login(env)
    sid = client.cookies[cfg.cookie_name]
    assert client.post("/logout", data={"csrf": "wrong"}).status_code == 400
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/logout").text)[1]
    assert client.post("/logout", data={"csrf": csrf}, headers={"Origin": "http://evil.test"}).status_code == 403
    response = client.post("/logout", data={"csrf": csrf}, headers={"Origin": cfg.public_url})
    assert response.status_code == 303
    assert urlsplit(response.headers["location"]).path.endswith("/logout")
    assert redis.hgetall(PREFIX + "sess:" + sid) == {}
    assert redis.smembers(_user_key("subject-1")) == set()
    client.cookies.set(cfg.cookie_name, sid, domain="localhost.local", path="/")
    assert client.get("/me").status_code == 401


def test_missing_login_cookie_state_replay_and_rotation(env):
    client, _app, cfg, redis, _state, _now = env
    assert client.get("/oidc/callback?state=bad&code=code").status_code == 400
    state = start(env)
    client.cookies.delete(cfg.login_cookie)
    assert client.get("/oidc/callback", params={"state": state, "code": "code"}).status_code == 400
    state = start(env)
    lid = client.cookies[cfg.login_cookie]
    assert client.get("/oidc/callback", params={"state": "bad", "code": "code"}).status_code == 400
    client.cookies.set(cfg.login_cookie, lid, domain="localhost.local", path="/")
    assert client.get("/oidc/callback", params={"state": state, "code": "code"}).status_code == 400
    login(env)
    old = client.cookies[cfg.cookie_name]
    login(env)
    assert client.cookies[cfg.cookie_name] != old
    assert redis.hgetall(PREFIX + "sess:" + old) == {}
    assert redis.smembers(_user_key("subject-1")) == {client.cookies[cfg.cookie_name]}


@pytest.mark.parametrize("overrides", [{"iss": "wrong"}, {"aud": "wrong"}, {"nonce": "wrong"}, {"exp": 1}])
def test_bad_id_tokens_fail_closed(env, overrides):
    env[4]["overrides"] = overrides
    assert login(env).status_code == 400
    assert env[3].keys(PREFIX + "sess:*") == []


def test_redis_failure(env, monkeypatch):
    client, _app, _cfg, redis, _state, _now = env
    login(env)
    def fail(*args, **kwargs):
        raise RedisConnectionError("down")
    monkeypatch.setattr(redis, "hgetall", fail)
    response = client.get("/me")
    assert response.status_code == 503 and response.headers["content-type"].startswith("application/problem+json")
    monkeypatch.setattr(redis, "ping", fail)
    assert client.get("/readyz").status_code == 503
    assert client.get("/healthz").status_code == 200


def test_cookie_secure_and_demo_disabled(env):
    _client, _app, cfg, redis, _state, _now = env
    cfg = replace(cfg, public_url="https://gateway.test", oidc=replace(cfg.oidc,
                  redirect_uri="https://gateway.test/oidc/callback", post_logout_redirect_uri="https://gateway.test/"),
                  cookie_secure=True, cookie_name="__Host-sid", login_cookie="__Host-login", demo_enabled=False)
    class Stub:
        def authorization_url(self, **kwargs):
            return "https://idp.test/login"
    with TestClient(create_app(cfg, redis_client=redis, oidc_client=Stub()), base_url=cfg.public_url) as client:
        response = client.get("/login", follow_redirects=False)
        assert "; Secure" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]
        assert client.get("/demo").status_code == 404


def test_migrated_login_roles_redirect_cookie_and_jwks_cache(env):
    client, _app, cfg, _redis, _state, _now = env
    state = start(env, "/apps/noten/")
    response = client.get("/oidc/callback", params={"state": state, "code": "code"})
    assert response.status_code == 302
    assert response.headers["location"] == "/apps/noten/"
    session_cookie = next(v for v in response.headers.get_list("set-cookie") if v.startswith(cfg.cookie_name + "="))
    assert "max-age" not in session_cookie.lower()
    assert client.get("/me").json()["roles"] == ["student"]
    assert client.get("/.well-known/jwks.json").headers["cache-control"] == "public, max-age=300"


def test_migrated_unsafe_next_and_default_target(env):
    client = env[0]
    state = start(env, "https://evil.test/")
    response = client.get("/oidc/callback", params={"state": state, "code": "code"})
    assert response.status_code == 302 and response.headers["location"] == "/"


def test_migrated_logout_anonymous_and_allow_header(env):
    client = env[0]
    response = client.get("/logout")
    assert response.status_code == 302 and response.headers["location"] == "/"
    response = client.post("/logout", data={"csrf": "invalid"})
    assert response.status_code == 303 and response.headers["location"] == "/"
    response = client.post("/me")
    assert response.status_code == 405
    assert "GET" in response.headers["allow"]


@pytest.fixture
def routed(env, tmp_path):
    from gateway.config import AppsConfig
    from gateway.registry_client import RegistryClient
    source_client, _source_app, cfg, redis, _idp_state, now = env
    login(env)
    sid = source_client.cookies[cfg.cookie_name]
    cfg = replace(cfg, apps=AppsConfig('http://{slug}.apps.test:8080'))
    policy = {'value': {'slug': 'noten', 'roles': ['student'], 'status': 'healthy', 'adapters': ['noten:read']},
              'failure': False}
    lookups, forwarded = [], []
    secret = tmp_path / 'service-token'
    secret.write_text('registry-test-only-' + 'x' * 32)
    def registry_response(request):
        lookups.append(request)
        if policy['failure']:
            return httpx.Response(503)
        assert request.method == 'POST' and request.url.path == '/internal/apps/noten/authorize'
        claims = app.state.assertions.keys.verify(request.headers['x-portal-assertion'], cfg.portal_audience)
        assert claims['token_use'] == 'portal-ui'
        value = policy['value']
        if value is None or value.get('status') in ('registering', 'failed', 'retired'):
            return httpx.Response(404, json={'slug': 'noten', 'allowed': False, 'reason': 'not_found'})
        if 'roles' not in value:
            return httpx.Response(200, json=value)
        if not set(value['roles']) & set(claims['roles']):
            return httpx.Response(403, json={'slug': 'noten', 'allowed': False, 'reason': 'forbidden'})
        if value['status'] != 'healthy':
            return httpx.Response(503, json={'slug': 'noten', 'allowed': False, 'reason': 'unavailable'})
        return httpx.Response(200, json={'slug': 'noten', 'allowed': True, 'adapters': value['adapters']})
    registry = RegistryClient('http://portal-registry:8000', secret,
                              transport=httpx.MockTransport(registry_response))
    def upstream(request):
        forwarded.append(request)
        return httpx.Response(200, json={'ok': True}, headers={'Set-Cookie': 'app=secret; Path=/'})
    class UnusedOidc:
        pass
    app = create_app(cfg, redis_client=redis, oidc_client=UnusedOidc(), registry_client=registry,
                     app_transport=httpx.MockTransport(upstream), clock=lambda: now[0])
    try:
        with TestClient(app, base_url=cfg.public_url, follow_redirects=False) as client:
            client.cookies.set(cfg.cookie_name, sid)
            yield client, app, cfg, redis, policy, lookups, forwarded, now
        assert app.state.proxy.client.is_closed
    finally:
        registry.close()


def test_app_route_authorizes_and_replaces_browser_credentials(routed):
    client, app, _cfg, _redis, _policy, lookups, forwarded, _now = routed
    response = client.get('/apps/noten/?semester=1', headers={'Authorization': 'Bearer browser-token',
                                                            'X-Portal-Assertion': 'forged'})
    assert response.status_code == 200
    assert len(lookups) == len(forwarded) == 1
    request = forwarded[0]
    assert str(request.url) == 'http://noten.apps.test:8080/apps/noten/?semester=1'
    assert 'authorization' not in request.headers and 'cookie' not in request.headers
    claims = app.state.assertions.keys.verify(request.headers['x-portal-assertion'], 'noten')
    assert claims['sub'] == 'subject-1' and claims['roles'] == ['student']
    assert claims['aud'] == ['noten', 'portal', 'adapters'] and claims['scp'] == ['noten:read']
    assert claims['exp'] - claims['iat'] == 60
    assert 'set-cookie' not in response.headers
    assert list(app.state.proxy.client.cookies.jar) == []


def test_app_route_reads_each_policy_and_never_forwards_denied_requests(routed):
    client, _app, _cfg, _redis, policy, lookups, forwarded, _now = routed
    assert client.get('/apps/noten/').status_code == 200
    policy['value']['roles'] = ['employee']
    assert client.get('/apps/noten/').status_code == 403
    policy['value']['roles'] = ['student']
    policy['value']['status'] = 'unhealthy'
    assert client.get('/apps/noten/').status_code == 503
    policy['value']['status'] = 'registering'
    assert client.get('/apps/noten/').status_code == 404
    policy['value'] = None
    assert client.get('/apps/noten/').status_code == 404
    policy['value'] = {'invalid': 'response'}
    assert client.get('/apps/noten/').status_code == 503
    policy['failure'] = True
    assert client.get('/apps/noten/').status_code == 503
    assert len(lookups) == 7 and len(forwarded) == 1


def test_app_route_anonymous_expired_and_cross_site_requests(routed):
    client, _app, cfg, _redis, _policy, _lookups, forwarded, now = routed
    assert client.post('/apps/noten/', data='body', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert forwarded == []
    sid = client.cookies[cfg.cookie_name]
    client.cookies.clear()
    response = client.get('/apps/noten/', headers={'X-Portal-Assertion': 'forged'})
    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=/apps/noten/'
    client.cookies.set(cfg.cookie_name, sid)
    now[0] += 301
    assert client.get('/apps/noten/').status_code == 302
    assert forwarded == []


def test_app_route_preserves_methods_and_trailing_slash(routed):
    client, _app, _cfg, _redis, _policy, lookups, forwarded, _now = routed
    response = client.get('/apps/noten')
    assert response.status_code == 308 and response.headers['location'] == '/apps/noten/'
    assert not lookups and not forwarded
    for method in ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'):
        response = client.request(method, '/apps/noten/', content=b'payload')
        assert response.status_code == 200
        assert forwarded[-1].method == method and forwarded[-1].content == b'payload'
    assert len(lookups) == len(forwarded) == 7


def test_app_route_fails_closed_without_configuration(env):
    client = env[0]
    assert client.get('/apps/noten/').status_code == 503


def test_app_route_fails_closed_when_redis_is_unavailable(routed, monkeypatch):
    client, _app, _cfg, redis, _policy, lookups, forwarded, _now = routed
    def fail(*args, **kwargs):
        raise RedisConnectionError('unavailable')
    monkeypatch.setattr(redis, 'hgetall', fail)
    assert client.get('/apps/noten/').status_code == 503
    assert not forwarded and not lookups


def test_logout_form_preserves_origin_and_logout_invalidates_session(env):
    client, app, cfg, redis, _state, _now = env
    login(env)
    sid = client.cookies[cfg.cookie_name]
    confirmation = client.get('/logout')
    assert confirmation.status_code == 200
    # Browsers serialize Origin as null on non-CORS form POSTs with no-referrer.
    # Keep this policy local to the form; callbacks and other pages stay private.
    assert confirmation.headers['referrer-policy'] == 'same-origin'
    assert client.get('/').headers['referrer-policy'] == 'no-referrer'
    csrf = re.search(r'name="csrf" value="([^"]+)"', confirmation.text)[1]
    response = client.post('/logout', data={'csrf': csrf}, headers={
        'Origin': cfg.public_url, 'Sec-Fetch-Site': 'same-origin',
    })
    assert response.status_code == 303
    assert urlsplit(response.headers['location']).path.endswith('/logout')
    assert redis.hgetall(PREFIX + 'sess:' + sid) == {}
    assert app.state.sessions.get(sid) is None
    assert any(v.startswith(cfg.cookie_name + '=') and 'Max-Age=0' in v
               for v in response.headers.get_list('set-cookie'))
    assert client.get('/me').status_code == 401


@pytest.mark.parametrize('origin,site', [
    ('http://evil.test', 'cross-site'),
    ('http://localhost:18081', 'same-site'),
    ('https://localhost:18080', 'same-site'),
    ('http://localhost:18080.evil.test', 'same-origin'),
    ('null', 'same-origin'),
    ('http://evil.test', 'same-origin'),
    ('http://localhost:18080', 'cross-site'),
    ('http://localhost:18080', 'same-site'),
])
def test_logout_rejects_foreign_and_null_origins_without_revoking_session(env, origin, site):
    client, app, cfg, _redis, _state, _now = env
    login(env)
    sid = client.cookies[cfg.cookie_name]
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get('/logout').text)[1]
    response = client.post('/logout', data={'csrf': csrf}, headers={'Origin': origin, 'Sec-Fetch-Site': site})
    assert response.status_code == 403
    assert app.state.sessions.get(sid) is not None
    assert client.get('/me').status_code == 200


def test_logout_still_requires_csrf_for_same_origin_form(env):
    client, app, cfg, _redis, _state, _now = env
    login(env)
    sid = client.cookies[cfg.cookie_name]
    response = client.post('/logout', data={'csrf': 'wrong'}, headers={
        'Origin': cfg.public_url, 'Sec-Fetch-Site': 'same-origin',
    })
    assert response.status_code == 400
    assert app.state.sessions.get(sid) is not None


def test_home_starts_oidc_and_returns_to_authenticated_demo(env):
    client, _app, cfg, _redis, state, _now = env
    response = client.get("/")
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert location.netloc == urlsplit(cfg.oidc.issuer).netloc
    query = parse_qs(location.query)
    assert query["code_challenge_method"] == ["S256"]
    state["nonce"], state["challenge"] = query["nonce"][0], query["code_challenge"][0]
    assert "httponly" in response.headers["set-cookie"].lower()
    callback = client.get("/oidc/callback", params={"state": query["state"][0], "code": "code"})
    assert callback.status_code == 302 and callback.headers["location"] == "/"
    response = client.get("/")
    assert response.status_code == 302 and response.headers["location"] == "/demo"
    assert client.get("/demo").json()["signature_verified"] is True


def test_home_restarts_login_after_session_expiry(env):
    client, _app, _cfg, _redis, _state, now = env
    login(env)
    now[0] += 301
    response = client.get("/")
    assert response.status_code == 302
    assert urlsplit(response.headers["location"]).path.endswith("/auth")


def test_home_does_not_trust_browser_identity_headers(env):
    response = env[0].get("/", headers={"X-Portal-Assertion": "forged"})
    assert response.status_code == 302
    assert urlsplit(response.headers["location"]).path.endswith("/auth")


@pytest.fixture
def portal_routed(env, tmp_path):
    client, _app, cfg, redis, _state, now = env
    login(env)
    sid = client.cookies[cfg.cookie_name]
    secret = tmp_path / 'service-token'
    secret.write_text('s' * 43)
    cfg = replace(cfg, portal_upstream='http://portal:8000', registry_url='http://portal:8000',
                  registry_token_file=secret, demo_enabled=False)
    calls = []
    state = {'failure': False}
    def portal(request):
        calls.append(request)
        if state['failure']:
            raise httpx.ConnectError('unavailable', request=request)
        return httpx.Response(200, json={'ok': True}, headers={'Set-Cookie': 'portal=forbidden'})
    class UnusedOidc:
        pass
    app = create_app(cfg, redis_client=redis, oidc_client=UnusedOidc(),
                     portal_transport=httpx.MockTransport(portal), clock=lambda: now[0])
    with TestClient(app, base_url=cfg.public_url, follow_redirects=False) as browser:
        browser.cookies.set(cfg.cookie_name, sid)
        yield browser, app, cfg, calls, state


def test_portal_forwarding_fresh_assertions_and_no_browser_credentials(portal_routed):
    client, app, cfg, calls, _state = portal_routed
    for path in ('/', '/_portal/admin'):
        response = client.get(path, headers={'Authorization': 'Bearer attacker', 'X-Portal-Assertion': 'forged',
                                            'X-Gateway-Context': 'forged'})
        assert response.status_code == 200 and 'set-cookie' not in response.headers
    claims = []
    for call in calls:
        assert 'authorization' not in call.headers and 'cookie' not in call.headers
        assert 'x-gateway-context' not in call.headers
        claims.append(app.state.assertions.keys.verify(call.headers['x-portal-assertion'], cfg.portal_audience))
    assert claims[0]['jti'] != claims[1]['jti']
    assert all(c['token_use'] == 'portal-ui' and c['exp'] - c['iat'] == 60 and c['csrf'] for c in claims)


def test_portal_origin_and_network_failure_fail_closed(portal_routed):
    client, _app, cfg, calls, state = portal_routed
    for origin in ('null', 'https://evil.invalid', 'https://localhost:18080'):
        assert client.post('/_portal/admin', headers={'Origin': origin}).status_code == 403
    assert calls == []
    assert client.post('/_portal/admin', headers={'Origin': cfg.public_url}).status_code == 200
    state['failure'] = True
    assert client.get('/').status_code == 503
    count = len(calls)
    assert client.get('/internal/apps/noten/access').status_code == 404
    assert client.post('/internal/apps/noten/authorize').status_code == 404
    assert len(calls) == count


def test_logout_dialog_without_token_needs_both_same_origin_signals(env):
    # SDK-Seitenrahmen der Apps: POST /logout ohne CSRF-Token, nur mit Origin + Sec-Fetch-Site der eigenen Herkunft.
    client, app, cfg, _redis, _state, _now = env
    login(env)
    sid = client.cookies[cfg.cookie_name]
    for headers in ({}, {'Origin': cfg.public_url}, {'Sec-Fetch-Site': 'same-origin'},
                    {'Origin': cfg.public_url, 'Sec-Fetch-Site': 'none'}):
        response = client.post('/logout', headers=headers)
        assert response.status_code == 303 and response.headers['location'] == '/logout'  # Bestätigungsseite
        assert app.state.sessions.get(sid) is not None
    for headers in ({'Origin': 'http://evil.test', 'Sec-Fetch-Site': 'same-origin'},
                    {'Origin': cfg.public_url, 'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'null'}):
        assert client.post('/logout', headers=headers).status_code == 403
        assert app.state.sessions.get(sid) is not None
    response = client.post('/logout', headers={'Origin': cfg.public_url, 'Sec-Fetch-Site': 'same-origin'})
    assert response.status_code == 303 and urlsplit(response.headers['location']).path.endswith('/logout')
    assert app.state.sessions.get(sid) is None
    assert client.get('/me').status_code == 401


def test_oidc_client_keeps_no_cookies():
    """Ein Client für alle Personen: Cookies des IdP werden weder gespeichert noch mitgeschickt."""
    seen = []

    def idp(request):
        seen.append(request.headers.get("cookie"))
        return httpx.Response(200, json={"ok": len(seen)},
                              headers={"Set-Cookie": f"AUTH_SESSION_ID=sitzung-{len(seen)}; Path=/"})

    oidc = OidcClient(OidcConfig("http://idp.test/realms/test", "gateway", "test-only", "http://gw.test/cb",
                                 "http://gw.test/"), transport=httpx.MockTransport(idp))
    try:
        assert oidc._get_json("http://idp.test/eins") == {"ok": 1}
        assert oidc._get_json("http://idp.test/zwei") == {"ok": 2}
        assert seen == [None, None] and len(oidc._http.cookies) == 0
    finally:
        oidc.close()


def test_logout_without_session_redirects_home_and_clears_cookie(env):
    """HKA-118 AK1: alter Tab oder schon abgemeldet -> 303 auf /, Cookie gelöscht, kein 400."""
    client, cfg = env[0], env[2]
    for headers in ({}, {"Origin": cfg.public_url, "Sec-Fetch-Site": "same-origin"}):
        client.cookies.set(cfg.cookie_name, "x" * 43)
        response = client.post("/logout", data={"csrf": "egal"}, headers=headers)
        assert response.status_code == 303 and response.headers["location"] == "/"
        assert f'{cfg.cookie_name}=""' in response.headers["set-cookie"] and "Max-Age=0" in response.headers["set-cookie"]
    client.cookies.clear()
    response = client.post("/logout")
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert "set-cookie" not in response.headers
