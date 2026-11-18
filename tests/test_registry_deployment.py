"""Registry- und Netzverdrahtung des Gesamtstarts (server/compose.yml), ohne Dienste zu starten.

Früher: Opt-in-Dateien compose.registry.yml/compose.portal.yml. Jetzt bindet server/compose.yml die Bausteine
gateway/, redis/, keycloak/, Portal-Backend und Adapter per include ein; geprüft wird dieselbe Absicht:
Registry nur intern, Service-Token nur für Gateway und Portal, keine offenen Ports außer Gateway und Keycloak.
"""
import unittest

from compose_config import PORTAL, ROOT, config, members, require_stack


class RegistryDeploymentTests(unittest.TestCase):
    def test_public_nginx_denies_internal_routes(self):
        if not PORTAL.exists():
            self.skipTest('Sibling portal repository unavailable')
        text = (PORTAL / 'extras/compose/vm/nginx-portal.conf').read_text()
        self.assertIn('location = /internal { return 404; }', text)
        self.assertIn('location ^~ /internal/ { return 404; }', text)

    def test_registry_is_internal_and_token_only_shared_by_gateway_and_portal(self):
        require_stack(self)
        document = config(ROOT / 'server/compose.yml')
        services = document['services']
        self.assertEqual(set(services), {'gateway', 'gateway-redis', 'keycloak', 'backend', 'adapter'})
        gateway = services['gateway']['environment']
        self.assertEqual(gateway['GW_REGISTRY_URL'], 'http://backend:8000')
        self.assertEqual(gateway['GW_PORTAL_UPSTREAM'], 'http://backend:8000')
        self.assertEqual(gateway['GW_REGISTRY_SERVICE_TOKEN_FILE'], '/run/secrets/registry_service_token')
        self.assertEqual(members(document, 'portal'), {'gateway', 'backend'})
        self.assertTrue(document['networks']['portal']['internal'])
        holders = {name for name, s in services.items()
                   if 'registry_service_token' in {x['source'] for x in s.get('secrets', [])}}
        self.assertEqual(holders, {'gateway', 'backend'})
        self.assertEqual(document['secrets']['registry_service_token']['file'], '/test/secrets/registry-service-token')

    def test_portal_apps_and_adapter_have_no_published_ports(self):
        require_stack(self)
        document = config(ROOT / 'server/compose.yml')
        services = document['services']
        for name in ('backend', 'adapter', 'gateway-redis'):
            self.assertFalse(services[name].get('ports'), name)
        for name in ('gateway', 'keycloak'):
            self.assertTrue(services[name]['ports'])
            for port in services[name]['ports']:
                self.assertEqual(port['host_ip'], '127.0.0.1')
        # Apps kommen per deploy-local in das feste interne Netz hka-portal-apps
        self.assertEqual(document['networks']['apps']['name'], 'hka-portal-apps')
        self.assertTrue(document['networks']['apps']['internal'])
        self.assertEqual(members(document, 'apps'), {'gateway', 'backend', 'adapter'})
        self.assertEqual(set(services['backend']['networks']), {'portal', 'apps'})
        self.assertEqual(set(services['adapter']['networks']), {'apps', 'bwsync-egress'})
        # Private Schlüssel nur dort, wo sie gebraucht werden
        for name, service in services.items():
            sources = {x['source'] for x in service.get('secrets', [])}
            if name != 'gateway':
                self.assertNotIn('signing_key', sources, name)
                self.assertNotIn('oidc_secret', sources, name)
            if name != 'adapter':
                self.assertNotIn('bwsync_credentials_key', sources, name)


if __name__ == '__main__':
    unittest.main()
