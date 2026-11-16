"""Die Kit-Kopie für das Keycloak-Theme ist vollständig und unverändert (tools/keycloak_theme.py)."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("keycloak_theme", ROOT / "tools" / "keycloak_theme.py")
keycloak_theme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keycloak_theme)


class KeycloakThemeKitTest(unittest.TestCase):
    def test_copy_matches_its_checksum(self):
        version = keycloak_theme.check(keycloak_theme.TARGET)
        self.assertRegex(version, r"^\d+\.\d+\.\d+")

    def test_changed_copy_is_detected(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "theme-kit"
            shutil.copytree(keycloak_theme.TARGET, copy)
            (copy / "kit.css").write_text("/* geändert */\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                keycloak_theme.check(copy)


if __name__ == "__main__":
    unittest.main()
