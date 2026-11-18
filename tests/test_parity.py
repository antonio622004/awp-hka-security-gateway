"""Abgleich Gateway <-> Portal an der heutigen Grenze, ohne Dienste zu starten.

Früher verglich dieser Test Gateway-Code mit den Login-, Rollen- und Schlüsselklassen des Portals. Diese gibt es
im Portal nicht mehr: Anmeldung, OIDC, Sessions und Signierschlüssel liegen nur im Gateway, das Portal prüft nur
noch dessen Assertions (``portal/auth/gateway.py``). Geprüft wird deshalb der Vertrag an dieser Grenze:

* vom Gateway ausgestellte Assertions nimmt der echte Portal-Verifier an (Portal-UI und SDK-Navigation),
* Weiterleitungsziele nach der Anmeldung gleich wie im Portal (``auth/redirects.py``),
* Rollenvokabular, Issuer, öffentliche URL und Audience passen in beiden Konfigurationen zusammen,
* das Portal nimmt keine eigene OIDC-Konfiguration mehr an (keine zweite Anmeldung).
"""
import ast
import importlib.util
import json
import re
import secrets
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from gateway.assertions import Assertions
from gateway.redirects import sanitize_next
from gateway.sessions import Session

ROOT = Path(__file__).resolve().parents[1]
PORTAL_REPO = ROOT.parent / 'awp-hka-intranet-portal'
PORTAL = PORTAL_REPO / 'src/portal'
ROLE_VOCABULARY = ('student', 'employee', 'professor', 'platform-admin', 'pilot-tester')


def portal_module(relative: str):
    """Ein einzelnes Portal-Modul aus dem Nachbar-Repo laden (ohne das Paket ``portal`` zu importieren)."""
    path = PORTAL / relative
    if not path.exists():
        raise unittest.SkipTest(f'Portal source unavailable: {path}')
    name = '_portal_' + relative.replace('/', '_').removesuffix('.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def portal_config(name: str) -> dict:
    path = PORTAL_REPO / 'dev' / name
    if not path.exists():
        raise unittest.SkipTest(f'Portal config unavailable: {path}')
    return yaml.safe_load(path.read_text())


def gateway_compose_env() -> dict:
    """Standardwerte aus gateway/compose.yml (``${NAME:-wert}``) und feste Werte."""
    service = yaml.safe_load((ROOT / 'gateway/compose.yml').read_text())['services']['gateway']['environment']
    values = {}
    for key, value in service.items():
        match = re.fullmatch(r'\$\{[A-Z_]+:-(.*)\}', str(value))
        values[key] = match.group(1) if match else str(value)
    return values


class PortalParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        key = rsa.generate_private_key(65537, 2048)
        cls.key_path = Path(cls.directory.name) / 'signing-key.pem'
        cls.key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def verifier_for(self, assertions: Assertions, issuer: str):
        module = portal_module('auth/gateway.py')
        jwks = json.dumps(assertions.jwks()).encode()
        http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=jwks)))
        cfg = SimpleNamespace(issuer=issuer, jwks_url='http://gateway:8080/.well-known/jwks.json',
                              public_url=issuer.rstrip('/'), audience='hka-portal-ui')
        return module.GatewayVerifier(cfg, http=http), http

    def test_portal_accepts_gateway_assertions(self):
        issuer = 'https://gateway.test/'
        assertions = Assertions(self.key_path, issuer, 'hka-portal-ui', role_vocabulary=ROLE_VOCABULARY)
        verifier, http = self.verifier_for(assertions, issuer)
        try:
            session = Session('sid', 'subject-1', 'Erika Muster', frozenset({'student', 'pilot-tester'}),
                              secrets.token_urlsafe(16))
            user = verifier.verify(assertions.mint(session))
            self.assertEqual((user.sub, user.name, user.roles, user.csrf),
                             ('subject-1', 'Erika Muster', frozenset({'student', 'pilot-tester'}), session.csrf))
            # App-Assertions tragen nur Rollen aus dem Vokabular
            mixed = Session('sid', 'subject-1', 'Erika Muster', frozenset({'student', 'unmapped'}), session.csrf)
            app = SimpleNamespace(slug='syncshare-test', adapters=('bwsync:read',))
            navigation = verifier.verify(assertions.mint_app(mixed, app), navigation=True)
            self.assertEqual(navigation.roles, frozenset({'student'}))
            # Eine App-Assertion öffnet keine Portal-Seite, eine Portal-Assertion ist keine Navigation
            with self.assertRaises(Exception):
                verifier.verify(assertions.mint_app(session, app))
            with self.assertRaises(Exception):
                verifier.verify(assertions.mint(session), navigation=True)
        finally:
            http.close()

    def test_portal_rejects_assertions_of_another_issuer(self):
        assertions = Assertions(self.key_path, 'https://other.test/', 'hka-portal-ui', role_vocabulary=ROLE_VOCABULARY)
        verifier, http = self.verifier_for(assertions, 'https://gateway.test/')
        try:
            session = Session('sid', 'subject-1', 'Name', frozenset({'student'}), secrets.token_urlsafe(16))
            with self.assertRaises(Exception):
                verifier.verify(assertions.mint(session))
        finally:
            http.close()

    def test_redirect_contract_matches_portal(self):
        original = portal_module('auth/redirects.py')
        for value in (None, '', '/', '/apps/noten/', '/apps/noten/?x=1', '//evil.test',
                      'https://evil.test', '/admin', '/apps/\\evil', '/apps/\r\nevil', '/' + 'a' * 513):
            with self.subTest(value=value):
                self.assertEqual(sanitize_next(value), original.sanitize_next(value))

    def test_local_configs_fit_together(self):
        portal = portal_config('gateway.compose.yml')
        gateway = gateway_compose_env()
        self.assertEqual(tuple(portal['role_vocabulary']), tuple(gateway['GW_ROLE_VOCABULARY'].split(',')))
        self.assertEqual(portal['gateway']['public_url'], gateway['GW_PUBLIC_URL'])
        self.assertEqual(portal['gateway']['issuer'], gateway['GW_PUBLIC_URL'] + '/')  # GW_ASSERTION_ISSUER-Standard
        self.assertEqual(portal['gateway'].get('audience', 'hka-portal-ui'), 'hka-portal-ui')
        jwks = httpx.URL(portal['gateway']['jwks_url'])
        self.assertIn(jwks.host, gateway['GW_INTERNAL_HOSTS'].split(','))
        self.assertEqual(portal['auth_mode'], 'gateway')
        self.assertEqual(portal['apps']['upstream'], gateway['GW_APP_UPSTREAM'])

    def test_vm_portal_config_fits_gateway_vocabulary(self):
        portal = portal_config('gateway.vm.yml')
        gateway = gateway_compose_env()
        self.assertEqual(tuple(portal['role_vocabulary']), tuple(gateway['GW_ROLE_VOCABULARY'].split(',')))
        self.assertEqual(portal['gateway']['issuer'], portal['gateway']['public_url'] + '/')
        self.assertTrue(portal['gateway']['public_url'].startswith('https://'))
        self.assertEqual(portal['auth_mode'], 'gateway')

    def test_portal_has_no_second_login(self):
        path = PORTAL / 'core/config.py'
        if not path.exists():
            self.skipTest('Sibling portal source is required for comparison')
        tree = ast.parse(path.read_text())
        keys = next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == '_KEYS' for t in node.targets))
        self.assertNotIn('oidc', keys)
        self.assertFalse((PORTAL / 'service/login_service.py').exists())
        self.assertFalse((PORTAL / 'auth/assertion_keys.py').exists())

    def test_gateway_does_not_duplicate_manifest_authorization(self):
        gateway = ROOT / 'src/gateway'
        self.assertFalse((gateway / 'app_service.py').exists())
        self.assertIn('registry.authorize(slug, assertions.mint(session))', (gateway / 'app.py').read_text())


if __name__ == '__main__':
    unittest.main()
