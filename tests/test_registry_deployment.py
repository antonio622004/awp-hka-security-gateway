"""Validate opt-in deployment wiring without starting or changing any services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT.parent / 'awp-hka-intranet-portal'


class RegistryDeploymentTests(unittest.TestCase):
    def test_public_nginx_denies_internal_routes(self):
        if not PORTAL.exists():
            self.skipTest('Sibling portal repository unavailable')
        text = (PORTAL / 'extras/compose/vm/nginx-portal.conf').read_text()
        self.assertIn('location = /internal { return 404; }', text)
        self.assertIn('location ^~ /internal/ { return 404; }', text)

    @unittest.skipUnless(shutil.which('docker'), 'Docker CLI unavailable')
    def test_opt_in_network_and_external_secret(self):
        if not PORTAL.exists():
            self.skipTest('Sibling portal repository unavailable')
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / 'service-token'
            token.write_text('test-only-' + 'x' * 43)
            env = {**os.environ, 'GW_LOCAL_DIR': directory, 'GW_OIDC_CLIENT_SECRET_FILE': str(token),
                   'GW_KEYCLOAK_NETWORK': 'test-existing-idp', 'HKA_REGISTRY_NETWORK': 'test-internal-registry',
                   'HKA_REGISTRY_SERVICE_TOKEN_FILE': str(token)}
            def config(base, extra):
                result = subprocess.run(['docker', 'compose', '-f', str(base), '-f', str(extra),
                                         'config', '--format', 'json'], env=env, capture_output=True,
                                        text=True, check=True)
                return json.loads(result.stdout)
            gateway = config(ROOT / 'compose.yml', ROOT / 'compose.registry.yml')
            portal = config(PORTAL / 'extras/compose/vm/compose.yml',
                            PORTAL / 'extras/compose/vm/compose.registry.yml')
        self.assertEqual(set(gateway['services']), {'gateway', 'gateway-redis'})
        self.assertEqual(set(portal['services']), {'backend', 'redis', 'keycloak'})
        self.assertEqual(set(gateway['services']['gateway']['networks']), {'sessions', 'identity', 'registry'})
        self.assertEqual(set(portal['services']['backend']['networks']), {'default', 'registry'})
        self.assertIn('portal-registry', portal['services']['backend']['networks']['registry']['aliases'])
        for document in (portal, gateway):
            self.assertTrue(document['networks']['registry']['external'])
            self.assertEqual(document['networks']['registry']['name'], 'test-internal-registry')
            self.assertEqual(document['secrets']['registry_service_token']['file'], str(token))
        self.assertEqual(gateway['services']['gateway']['environment']['GW_REGISTRY_URL'],
                         'http://portal-registry:8000')
        for document, name in ((portal, 'backend'), (gateway, 'gateway')):
            for port in document['services'][name]['ports']:
                self.assertEqual(port['host_ip'], '127.0.0.1')

    @unittest.skipUnless(shutil.which('docker'), 'Docker CLI unavailable')
    def test_isolated_portal_and_micro_app_have_no_published_ports(self):
        env = {**os.environ, 'GW_LOCAL_DIR': '/tmp/test-gateway',
               'GW_OIDC_CLIENT_SECRET_FILE': '/tmp/test-client-secret',
               'GW_KEYCLOAK_NETWORK': 'test-existing-idp',
               'HKA_REGISTRY_SERVICE_TOKEN_FILE': '/tmp/test-service-token'}
        result = subprocess.run(['docker', 'compose', '-f', str(ROOT / 'compose.yml'),
                                 '-f', str(ROOT / 'compose.portal.yml'), 'config', '--format', 'json'],
                                env=env, capture_output=True, text=True, check=True)
        document = json.loads(result.stdout)
        services = document['services']
        self.assertEqual(services['portal']['build']['dockerfile'], 'Dockerfile.local')
        for name in ('portal', 'app-syncshare-test', 'gateway-redis'):
            self.assertFalse(services[name].get('ports'))
        self.assertEqual(set(services['portal']['networks']), {'portal'})
        self.assertEqual(set(services['app-syncshare-test']['networks']), {'apps'})
        self.assertEqual(set(services['gateway']['networks']), {'portal', 'apps', 'sessions', 'identity'})
        self.assertTrue(document['networks']['portal']['internal'])
        self.assertTrue(document['networks']['apps']['internal'])
        self.assertNotIn('signing_key', {s['source'] for s in services['portal']['secrets']})


if __name__ == '__main__':
    unittest.main()
