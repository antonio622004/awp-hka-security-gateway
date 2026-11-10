"""Dependency-light tests: runnable with stdlib + PyJWT + cryptography."""
from pathlib import Path
import tempfile
import time
import unittest

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from gateway.assertions import Assertions, verify_portal_context
from gateway.config import ConfigError, OidcConfig, Settings
from gateway.redis_sessions import PREFIX, RedisSessionStore, RedisLoginStore, _user_key
from gateway.sessions import Session


class MemoryRedis:
    """Redis-command test double with hashes, sets, queued pipelines and expiry.

    Not a production fallback or a substitute for real Redis integration tests.
    """
    def __init__(self, clock):
        self.clock, self.values = clock, {}
        self.hset_calls = 0

    def set(self, key, value, ex):
        self.values[key] = (value, self.clock() + ex)

    def get(self, key):
        value = self.values.get(key)
        if value is None or self.clock() >= value[1]:
            self.values.pop(key, None)
            return None
        return value[0]

    def delete(self, key):
        self.values.pop(key, None)

    def getdel(self, key):
        value = self.get(key)
        self.delete(key)
        return value

    def hgetall(self, key):
        return dict(self.get(key) or {})

    def hget(self, key, field):
        return self.hgetall(key).get(field)

    def hset(self, key, field=None, value=None, mapping=None):
        self.hset_calls += 1
        data = self.hgetall(key)
        data.update({str(k): str(v) for k, v in (mapping if mapping is not None else {field: value}).items()})
        self.values[key] = (data, self.values.get(key, (None, float("inf")))[1])

    def expire(self, key, seconds):
        if self.get(key) is not None:
            self.values[key] = (self.values[key][0], self.clock() + seconds)

    def ttl(self, key):
        return int(self.values[key][1] - self.clock()) if self.get(key) is not None else -2

    def sadd(self, key, member):
        values = set(self.get(key) or ())
        values.add(member)
        self.values[key] = (values, self.values.get(key, (None, float("inf")))[1])

    def smembers(self, key):
        return set(self.get(key) or ())

    def srem(self, key, member):
        values = self.smembers(key)
        values.discard(member)
        if values:
            self.values[key] = (values, self.values[key][1])
        else:
            self.delete(key)

    def pipeline(self):
        redis = self

        class Pipeline:
            def __init__(self):
                self.queue = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def __getattr__(self, name):
                def enqueue(*args, **kwargs):
                    self.queue.append((name, args, kwargs))
                    return self
                return enqueue

            def execute(self):
                results = [getattr(redis, name)(*args, **kwargs) for name, args, kwargs in self.queue]
                self.queue.clear()
                return results

        return Pipeline()


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.now = [int(time.time())]
        self.clock = lambda: self.now[0]
        self.redis = MemoryRedis(self.clock)
        self.store = RedisSessionStore(self.redis, idle_seconds=120, absolute_seconds=300,
                                        touch_min_interval_seconds=60, clock=self.clock)
        self.login_store = RedisLoginStore(self.redis, ttl_seconds=10)
        self.claims = {"sub": "demo-sub", "name": "Demo", "roles": frozenset({"student"})}

    def create(self):
        return self.store.create(**self.claims, id_token="id-token-server-only")

    def test_create_hash_ttl_user_index_and_metadata(self):
        session = self.create()
        key = PREFIX + "sess:" + session.sid
        self.assertEqual(self.redis.ttl(key), 120)
        self.assertEqual(self.redis.ttl(_user_key(session.sub)), 300)
        self.assertEqual(self.redis.smembers(_user_key(session.sub)), {session.sid})
        self.assertEqual(self.store.get(session.sid), session)
        self.assertEqual(session.expires_at, self.now[0] + 300)
        self.assertTrue(session.has_role("student"))
        self.assertTrue(session.csrf_matches(session.csrf))
        self.assertFalse(session.csrf_matches("wrong"))
        self.assertEqual(self.redis.hgetall(key)["id_token"], "id-token-server-only")

    def test_inactivity_timeout(self):
        session = self.create()
        self.now[0] += 121
        self.assertIsNone(self.store.get(session.sid))

    def test_activity_refreshes_idle_ttl_but_not_absolute_lifetime(self):
        session = self.create()
        key = PREFIX + "sess:" + session.sid
        for elapsed in (61, 122, 183, 244, 299):
            self.now[0] = session.expires_at - 300 + elapsed
            self.assertEqual(self.store.get(session.sid), session)
        self.assertGreater(self.redis.ttl(key), 0)
        self.now[0] = session.expires_at + 1
        self.assertIsNone(self.store.get(session.sid))
        self.assertEqual(self.redis.smembers(_user_key(session.sub)), set())

    def test_touch_writes_only_at_configured_interval(self):
        session = self.create()
        key = PREFIX + "sess:" + session.sid
        self.now[0] += 59
        for _ in range(100):
            self.store.get(session.sid)
        self.assertEqual(self.redis.hset_calls, 1)
        self.assertEqual(self.redis.ttl(key), 61)
        self.now[0] += 1
        self.store.get(session.sid)
        self.assertEqual(self.redis.hset_calls, 2)
        self.assertEqual(self.redis.ttl(key), 120)

    def test_delete_cleans_only_selected_session_and_user_index(self):
        first, second = self.create(), self.create()
        self.store.delete(first.sid)
        self.assertIsNone(self.store.get(first.sid))
        self.assertEqual(self.store.get(second.sid), second)
        self.assertEqual(self.redis.smembers(_user_key(first.sub)), {second.sid})
        self.store.delete(first.sid)  # idempotent

    def test_login_transaction_is_one_time_and_expires(self):
        self.login_store.put("lid", {"state": "state", "nonce": "nonce", "verifier": "verifier"})
        self.assertEqual(self.login_store.pop("lid")["nonce"], "nonce")
        self.assertIsNone(self.login_store.pop("lid"))
        self.login_store.put("lid", {"state": "x"})
        self.now[0] += 11
        self.assertIsNone(self.login_store.pop("lid"))

    def test_unknown_and_missing_session(self):
        for sid in (None, "", "unknown"):
            self.assertIsNone(self.store.get(sid))

    def test_old_json_sessions_are_not_read_as_hashes(self):
        sid = "x" * 43
        self.redis.set("hka-gateway:v1:sess:" + sid, '{"sub":"old"}', ex=300)
        self.assertIsNone(self.store.get(sid))
        self.assertIsNotNone(self.redis.get("hka-gateway:v1:sess:" + sid))

    def test_storage_errors_propagate_without_memory_fallback(self):
        class Broken:
            def hgetall(self, _key):
                raise ConnectionError("redis down")
        with self.assertRaises(ConnectionError):
            RedisSessionStore(Broken(), idle_seconds=120, absolute_seconds=300,
                              touch_min_interval_seconds=60).get("x" * 43)

    def test_signing_jwks_and_purpose_separation(self):
        with tempfile.TemporaryDirectory() as directory:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            path = Path(directory) / "key.pem"
            path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
            signer = Assertions(path, "https://gateway.test/", "hka-portal-ui")
            session = Session(sid="x" * 43, sub="demo-sub", name="Demo", roles=frozenset(), csrf="csrf")
            token = signer.mint(session)
            claims = verify_portal_context(token, signer.jwks(), "https://gateway.test/", "hka-portal-ui")
            self.assertEqual(claims["exp"] - claims["iat"], 60)
            self.assertEqual(claims["v"], 1)
            self.assertEqual(claims["token_use"], "portal-ui")
            self.assertEqual(jwt.get_unverified_header(token)["kid"], signer.kid)
            self.assertNotIn("d", signer.jwks()["keys"][0])
            app_token = signer.mint(session, purpose="micro-app", app_slug="noten")
            with self.assertRaises(jwt.InvalidTokenError):
                verify_portal_context(app_token, signer.jwks(), "https://gateway.test/", "hka-portal-ui")
            wrong_purpose = jwt.encode({**claims, "token_use": "micro-app"}, key, algorithm="RS256",
                                       headers={"kid": signer.kid})
            with self.assertRaises(jwt.InvalidTokenError):
                verify_portal_context(wrong_purpose, signer.jwks(), "https://gateway.test/", "hka-portal-ui")
            expired = jwt.encode({**claims, "iat": claims["iat"] - 120, "exp": claims["iat"] - 60},
                                 key, algorithm="RS256", headers={"kid": signer.kid})
            with self.assertRaises(jwt.ExpiredSignatureError):
                verify_portal_context(expired, signer.jwks(), "https://gateway.test/", "hka-portal-ui")
            with self.assertRaises(ValueError):
                signer.mint(session, purpose="micro-app", app_slug="hka-portal-ui")
            other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            forged = jwt.encode(claims, other, algorithm="RS256", headers={"kid": signer.kid})
            with self.assertRaises(jwt.InvalidSignatureError):
                verify_portal_context(forged, signer.jwks(), "https://gateway.test/", "hka-portal-ui")

    def test_config_refuses_unsafe_public_origin(self):
        def settings(public, secure=True):
            return Settings(public, OidcConfig("https://idp.test", "gateway", "not-a-real-secret",
                                              public + "/oidc/callback", public + "/"),
                            Path("unused"), cookie_secure=secure)
        with self.assertRaises(ConfigError):
            settings("http://public.example")
        with self.assertRaises(ConfigError):
            settings("https://public.example", secure=False)
        self.assertTrue(settings("https://public.example").cookie_secure)

    def test_idle_configuration_and_no_memory_store(self):
        from dataclasses import replace
        import gateway.sessions as models
        cfg = Settings("https://gateway.test", OidcConfig("https://idp.test", "gateway", "test-only",
                       "https://gateway.test/oidc/callback", "https://gateway.test/"), Path("unused"))
        self.assertEqual(replace(cfg, idle_seconds=120, touch_min_interval_seconds=10).session_seconds, 300)
        with self.assertRaises(ConfigError):
            replace(cfg, idle_seconds=30, touch_min_interval_seconds=60)
        self.assertFalse(hasattr(models, "MemorySessionStore"))
        self.assertFalse(hasattr(models, "Sessions"))


if __name__ == "__main__":
    unittest.main()
