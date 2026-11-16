"""Keycloak als Baustein des Gateways (keycloak/), eingebunden über gateway/compose.yml.

Früher: Wiederverwendung eines fremden Keycloak-Netzes (GW_KEYCLOAK_NETWORK). Jetzt gehört Keycloak zum
Gateway-Repo; geprüft wird dieselbe Absicht: genau ein Realm aus dem Repo, nur das Gateway spricht intern mit
Keycloak, der Browser erreicht ihn nur über Loopback, Sessions bleiben getrennt in gateway-redis.
"""
import json
import unittest

from compose_config import ROOT, config, members, require_stack


class KeycloakBuildingBlockTests(unittest.TestCase):
    def test_image_imports_only_the_repository_realm(self):
        dockerfile = (ROOT / 'keycloak/Dockerfile').read_text()
        self.assertIn('COPY hka-realm.json /opt/keycloak/data/import/hka-realm.json', dockerfile)
        self.assertEqual(dockerfile.count('/opt/keycloak/data/import/'), 1)
        self.assertFalse((ROOT / 'dev/hka-gateway-dev-realm.json').exists())
        realm = json.loads((ROOT / 'keycloak/hka-realm.json').read_text())
        self.assertEqual(realm['realm'], 'hka')
        client = next(c for c in realm['clients'] if c['clientId'] == 'portal')
        self.assertFalse(client.get('publicClient', False))
        self.assertTrue(client.get('standardFlowEnabled', True))
        self.assertFalse(client.get('directAccessGrantsEnabled', False))
        self.assertEqual(client.get('attributes', {}).get('pkce.code.challenge.method'), 'S256')

    def test_only_gateway_talks_to_keycloak_and_sessions_stay_separate(self):
        require_stack(self)
        document = config(ROOT / 'server/compose.yml')
        services = document['services']
        self.assertEqual(members(document, 'identity'), {'gateway', 'keycloak'})
        self.assertTrue(document['networks']['identity']['internal'])
        self.assertEqual(set(services['keycloak']['networks']), {'identity', 'keycloak-port'})
        self.assertEqual(members(document, 'sessions'), {'gateway', 'gateway-redis'})
        self.assertTrue(document['networks']['sessions']['internal'])
        gateway = services['gateway']['environment']
        self.assertEqual(gateway['GW_OIDC_ISSUER'], 'http://localhost:8180/realms/hka')
        self.assertEqual(gateway['GW_OIDC_DISCOVERY_URL'],
                         'http://keycloak:8080/realms/hka/.well-known/openid-configuration')
        self.assertEqual(gateway['GW_OIDC_CLIENT_ID'], 'portal')
        self.assertEqual(gateway['GW_REDIS_URL'], 'redis://gateway-redis:6379/0')
        keycloak = services['keycloak']['environment']
        self.assertEqual(keycloak['KC_HOSTNAME'], 'http://localhost:8180')
        self.assertEqual(keycloak['KC_HOSTNAME_BACKCHANNEL_DYNAMIC'], 'true')
        self.assertEqual([(p['host_ip'], p['published']) for p in services['keycloak']['ports']],
                         [('127.0.0.1', '8180')])


if __name__ == '__main__':
    unittest.main()
