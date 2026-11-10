"""Executable comparison with portal source, without starting either service.

Only imports are supplied by this harness: the original classes/functions execute
unchanged. This isolates their behavior from portal UI/package initialization.
It is not an HTTP, dependency-version, or deployment integration test.
"""
import ast
import base64
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Final, Mapping
import unittest
import uuid
from urllib.parse import quote

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from gateway.assertions import Assertions
from gateway.config import AssertionConfig, ConfigError, OidcConfig
from gateway.exceptions import (LoginFailedError, LoginRequiredError, ForbiddenError, NotFoundError, UnavailableError)
from gateway.redirects import sanitize_next
from gateway.roles import RoleMapper, RoleSource
from gateway.sessions import Session
from test_core import MemoryRedis
from gateway.redis_sessions import RedisLoginStore, RedisSessionStore

PORTAL = Path(__file__).resolve().parents[2] / 'awp-hka-intranet-portal/src/portal'
GATEWAY = Path(__file__).resolve().parents[1] / 'src/gateway'


def source_module(path, **dependencies):
    if not path.exists():
        raise unittest.SkipTest(f'Portal comparison source unavailable: {path}')
    module = ModuleType('_parity_' + path.stem + '_' + str(abs(hash(path))))
    sys.modules[module.__name__] = module
    module.__dict__.update({
        'dataclass': dataclass, 'field': field, 'Any': Any, 'Final': Final, 'Mapping': Mapping,
        'Path': Path, 'jwt': jwt, 'serialization': serialization, 'rsa': rsa, 'RSAAlgorithm': RSAAlgorithm,
        'base64': base64, 'hashlib': hashlib, 'json': json, 'time': time, 'uuid': uuid, 'secrets': secrets,
        'quote': quote, 'logger': SimpleNamespace(debug=lambda *a: None, info=lambda *a: None,
                                                warning=lambda *a: None),
        'AssertionConfig': AssertionConfig, 'ConfigError': ConfigError, 'TOKEN_VERSION': 1,
        'sanitize_next': sanitize_next, 'LoginFailedError': LoginFailedError, 'OidcError': RuntimeError,
        'LoginRequiredError': LoginRequiredError, 'ForbiddenError': ForbiddenError,
        'NotFoundError': NotFoundError, 'UnavailableError': UnavailableError, 'AppDTO': lambda app: app,
    })
    module.__dict__.update(dependencies)
    tree = ast.parse(path.read_text())
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))
                 or isinstance(node, ast.ImportFrom) and node.module == '__future__']
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    return module


class PortalParityTests(unittest.TestCase):
    def test_redirect_contract_matches_portal(self):
        original = source_module(PORTAL / 'auth/redirects.py')
        for value in (None, '', '/', '/apps/noten/', '/apps/noten/?x=1', '//evil.test',
                      'https://evil.test', '/admin', '/apps/\\evil', '/apps/\r\nevil', '/' + 'a' * 513):
            with self.subTest(value=value):
                self.assertEqual(sanitize_next(value), original.sanitize_next(value))

    def test_role_mapping_matches_portal(self):
        original = source_module(PORTAL / 'auth/roles.py')
        sources = (RoleSource('affiliation', {'student': 'student', 'faculty': 'professor'}),)
        grants = {'subject': frozenset({'pilot-tester'})}
        current = RoleMapper(sources, frozenset({'employee'}), grants)
        old = original.RoleMapper(sources, frozenset({'employee'}), grants)
        for subject, claims in [('subject', {}), ('other', {'affiliation': 'student'}),
                                ('subject', {'affiliation': ['faculty', 'unknown']}), ('other', {})]:
            self.assertEqual(current.map_roles(subject, claims), old.map_roles(subject, claims))

    def test_jwks_and_app_claims_match_portal(self):
        original_keys = source_module(PORTAL / 'auth/assertion_keys.py')
        original_service = source_module(PORTAL / 'service/assertion_service.py')
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index in range(3):
                path = Path(directory) / f'{index}.pem'
                key = rsa.generate_private_key(65537, 2048)
                path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                  serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
                paths.append(path)
            issuer = 'https://gateway.test/'
            cfg = AssertionConfig(issuer, 60, *paths)
            old_keys = original_keys.SigningKeys.load(cfg, dev=False)
            current = Assertions(paths[0], issuer, 'hka-portal-ui', role_vocabulary=('student',),
                                 next_key=paths[1], previous_key=paths[2])
            self.assertEqual(current.jwks(), old_keys.jwks())
            old_service = original_service.AssertionService(old_keys, cfg, ('student',))
            user = Session('sid', 'subject', 'Name', frozenset({'student', 'unmapped'}), 'csrf')
            for scopes in ((), ('grades:read',)):
                app = SimpleNamespace(slug='noten', adapters=scopes)
                old = old_keys.verify(old_service.mint(user, app), 'noten')
                new = current.keys.verify(current.mint_app(user, app), 'noten')
                for volatile in ('jti', 'iat', 'exp'):
                    old.pop(volatile)
                    new.pop(volatile)
                self.assertEqual(new, old)
                self.assertEqual(new['roles'], ['student'])
                self.assertNotIn('token_use', new)

    def test_login_orchestration_matches_portal(self):
        original = source_module(PORTAL / 'service/login_service.py')
        current = source_module(GATEWAY / 'login_service.py')
        roles = RoleMapper((RoleSource('affiliation', {'student': 'student'}),))

        class Idp:
            def authorization_url(self, **kwargs):
                return 'https://idp.test/authorize'

            def claims_for_code(self, **kwargs):
                return {'sub': 'subject', 'name': 'Name', 'affiliation': 'student'}, 'server-only'

        class PortalSessionAdapter:
            def __init__(self, store):
                self.store = store

            def discard(self, sid):
                self.store.delete(sid)

            def create_for_subject(self, **kwargs):
                return self.store.create(**kwargs)

        results = []
        for cls, portal in ((original.LoginService, True), (current.LoginService, False)):
            redis = MemoryRedis(time.time)
            sessions = RedisSessionStore(redis, idle_seconds=120, absolute_seconds=300,
                                         touch_min_interval_seconds=60)
            login_store = RedisLoginStore(redis, ttl_seconds=600)
            service = cls(Idp(), login_store, roles, PortalSessionAdapter(sessions) if portal else sessions)
            old = sessions.create('subject', 'Old', frozenset())
            started = service.start('/apps/noten/')
            record = json.loads(redis.get('hka-gateway:v2:oidc:' + started.lid))
            finished = service.finish(started.lid, 'code', record['state'], None, old.sid)
            self.assertIsNone(sessions.get(old.sid))
            with self.assertRaises(LoginFailedError):
                service.finish(started.lid, 'code', record['state'], None, None)
            results.append((finished.next, finished.session.sub, finished.session.roles, finished.session.id_token))
        self.assertEqual(*results)

    def test_gateway_does_not_duplicate_manifest_authorization(self):
        self.assertFalse((GATEWAY / 'app_service.py').exists())
        source = (GATEWAY / 'app.py').read_text()
        self.assertIn('registry.authorize(slug, assertions.mint(session))', source)

    def test_oidc_defaults_match_portal(self):
        if not (PORTAL / 'core/config.py').exists():
            self.skipTest('Sibling portal source is required for comparison')
        source = (PORTAL / 'core/config.py').read_text()
        tree = ast.parse(source)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'OidcConfig')
        defaults = {node.target.id: ast.literal_eval(node.value) for node in cls.body
                    if isinstance(node, ast.AnnAssign) and node.value is not None}
        self.assertEqual(OidcConfig.__dataclass_fields__['id_token_algs'].default, defaults['id_token_algs'])
        self.assertEqual(OidcConfig.__dataclass_fields__['clock_leeway_seconds'].default,
                         defaults['clock_leeway_seconds'])


if __name__ == '__main__':
    unittest.main()
