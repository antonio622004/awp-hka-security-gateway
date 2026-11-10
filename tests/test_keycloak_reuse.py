"""Configuration regression: reuse IdP, never provision/reset it."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ExistingKeycloakTests(unittest.TestCase):
    def test_no_realm_export_or_import_command(self):
        self.assertFalse((ROOT / "dev/hka-gateway-dev-realm.json").exists())
        compose = (ROOT / "compose.yml").read_text()
        self.assertNotIn("--import-realm", compose)
        self.assertNotIn("start-dev", compose)

    @unittest.skipUnless(shutil.which("docker"), "Docker CLI unavailable")
    def test_compose_reuses_network_and_keeps_sessions_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "client-secret"
            secret.write_text("test-placeholder-not-a-real-secret")
            env = {**os.environ, "GW_LOCAL_DIR": directory,
                   "GW_KEYCLOAK_NETWORK": "existing-test-network",
                   "GW_OIDC_CLIENT_SECRET_FILE": str(secret)}
            result = subprocess.run(["docker", "compose", "-f", str(ROOT / "compose.yml"),
                                     "config", "--format", "json"],
                                    env=env, capture_output=True, text=True, check=True)
            config = json.loads(result.stdout)
        self.assertEqual(set(config["services"]), {"gateway", "gateway-redis"})
        gateway = config["services"]["gateway"]["environment"]
        self.assertEqual(gateway["GW_OIDC_ISSUER"], "http://localhost:8180/realms/hka")
        self.assertEqual(gateway["GW_OIDC_CLIENT_ID"], "portal")
        self.assertEqual(gateway["GW_REDIS_URL"], "redis://gateway-redis:6379/0")
        self.assertTrue(config["networks"]["identity"]["external"])
        self.assertEqual(config["networks"]["identity"]["name"], "existing-test-network")


if __name__ == "__main__":
    unittest.main()
