"""VM-Stack (vm/compose.yml mit vm/.env.example), ohne Dienste zu starten: Werte der VM und ihr Zusammenspiel."""
import re
import unittest

import yaml

from compose_config import PORTAL, ROOT, config, members, require_stack

VM = ROOT / 'vm'


def env_example() -> dict[str, str]:
    values = {}
    for line in (VM / '.env.example').read_text().splitlines():
        if line and not line.startswith('#'):
            key, _, value = line.partition('=')
            values[key] = value
    return values


class VmComposeTests(unittest.TestCase):
    def setUp(self):
        require_stack(self)
        self.document = config(VM / 'compose.yml', env_file=VM / '.env.example')
        self.services = self.document['services']

    def test_same_services_as_local_stack_with_vm_values(self):
        self.assertEqual(self.document['name'], 'hka-vm')
        self.assertEqual(set(self.services), {'gateway', 'gateway-redis', 'keycloak', 'backend', 'adapter'})
        gateway = self.services['gateway']['environment']
        public = 'https://iwi-hean-05.hs-karlsruhe.de'
        self.assertEqual(gateway['GW_PUBLIC_URL'], public)
        self.assertEqual(gateway['GW_ASSERTION_ISSUER'], public + '/')
        self.assertEqual(gateway['GW_COOKIE_SECURE'], 'true')
        self.assertEqual(gateway['GW_DEMO_ENABLED'], 'false')
        self.assertEqual(gateway['GW_OIDC_ISSUER'], public + '/auth/realms/hka')
        self.assertEqual(gateway['GW_OIDC_DISCOVERY_URL'],
                         'http://keycloak:8080/auth/realms/hka/.well-known/openid-configuration')
        keycloak = self.services['keycloak']['environment']
        self.assertEqual(keycloak['KC_HTTP_RELATIVE_PATH'], '/auth')
        self.assertEqual(keycloak['KC_HOSTNAME'], public + '/auth')
        self.assertEqual(keycloak['KC_PROXY_HEADERS'], 'xforwarded')
        self.assertEqual(self.services['adapter']['environment']['BWSYNC_ASSERTION_ISSUER'], public + '/')
        self.assertEqual(self.services['backend']['environment']['PORTAL_CONFIG'], '/opt/app/dev/gateway.vm.yml')
        self.assertEqual(self.services['backend']['build']['dockerfile'], 'Dockerfile')

    def test_secrets_data_and_images_on_the_vm(self):
        secrets = {name: s['file'] for name, s in self.document['secrets'].items()}
        self.assertTrue(all(path.startswith('/srv/portal/gateway/secrets/') for path in secrets.values()), secrets)
        mounts = {v['target']: v['source'] for v in self.services['backend']['volumes']}
        self.assertEqual(mounts, {'/var/lib/portal/manifests': '/srv/portal/manifests',
                                  '/var/lib/portal/status': '/srv/portal/status',
                                  '/var/lib/portal/registry': '/srv/portal/registry'})
        roles = next(v for v in self.services['gateway']['volumes'] if v['target'] == '/run/config/roles.yml')
        self.assertEqual(roles['source'], '/srv/portal/gateway/roles.yml')
        for name, service in self.services.items():
            self.assertNotRegex(service['image'], r':local$', name)  # auf der VM nur geladene, getaggte Images

    def test_ports_only_on_loopback_and_networks_segmented(self):
        for name, service in self.services.items():
            for port in service.get('ports', []):
                self.assertEqual(port['host_ip'], '127.0.0.1', name)
        self.assertEqual({n for n, s in self.services.items() if s.get('ports')}, {'gateway', 'keycloak'})
        self.assertEqual(members(self.document, 'identity'), {'gateway', 'keycloak'})
        self.assertEqual(members(self.document, 'portal'), {'gateway', 'backend'})
        self.assertEqual(self.document['networks']['apps']['name'], 'hka-portal-apps')

    def test_vm_values_fit_portal_config_and_portal_deploy(self):
        values = env_example()
        portal = yaml.safe_load((PORTAL / 'dev/gateway.vm.yml').read_text())
        self.assertEqual(portal['gateway']['public_url'], values['GW_PUBLIC_URL'])
        self.assertEqual(portal['gateway']['issuer'], values['GW_PUBLIC_URL'] + '/')
        self.assertTrue(portal['cookie_secure'])
        deploy = (PORTAL / 'extras/compose/vm/deploy/deploy.env.example').read_text()
        image = re.search(r'^PORTAL_IMAGE=(\S+)', deploy, re.M).group(1)
        self.assertEqual(image, 'hka/portal:' + values['PORTAL_IMAGE_TAG'])
        nginx = (PORTAL / 'extras/compose/vm/nginx-portal.conf').read_text()
        self.assertIn('proxy_pass http://127.0.0.1:18080;', nginx)
        self.assertIn('proxy_pass        http://127.0.0.1:8180;', nginx)
        self.assertIn('location /auth/ {', nginx)


if __name__ == '__main__':
    unittest.main()
