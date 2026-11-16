"""Hilfen für Tests der Compose-Struktur: ``docker compose config`` mit Testwerten, ohne Dienste zu starten."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
PORTAL = WORKSPACE / 'awp-hka-intranet-portal'
ADAPTER = WORKSPACE / 'awp-hka-adapter'

# Nur Platzhalter: config prüft keine Dateiinhalte, die Secret-Dateien müssen nicht existieren.
TEST_ENV = {
    'GW_ROLES_SOURCE': '/test/roles.yml',
    'GW_OIDC_CLIENT_SECRET_SOURCE': '/test/secrets/oidc-client-secret',
    'GW_SIGNING_KEY_SOURCE': '/test/secrets/signing-key.pem',
    'HKA_REGISTRY_SERVICE_TOKEN_SOURCE': '/test/secrets/registry-service-token',
    'BWSYNC_CREDENTIALS_KEY_SOURCE': '/test/secrets/bwsync-credentials.key',
    'KC_BOOTSTRAP_ADMIN_PASSWORD': 'test-only-placeholder',
}


def require_stack(test: unittest.TestCase) -> None:
    """Überspringen, wenn Docker oder die Nachbar-Repositories fehlen (include braucht sie)."""
    if not shutil.which('docker'):
        test.skipTest('Docker CLI unavailable')
    for repo in (PORTAL, ADAPTER):
        if not repo.exists():
            test.skipTest(f'Sibling repository unavailable: {repo.name}')


def config(compose_file: Path, env: dict[str, str] | None = None, env_file: Path | None = None) -> dict:
    """Aufgelöste Compose-Konfiguration als JSON."""
    with tempfile.TemporaryDirectory() as directory:
        if env_file is None:
            env_file = Path(directory) / 'test.env'
            env_file.write_text(''.join(f'{k}={v}\n' for k, v in {**TEST_ENV, **(env or {})}.items()))
        # Nur Docker-Zugang aus der Shell übernehmen: Shell-Variablen hätten sonst Vorrang vor der env-Datei.
        shell = {k: v for k, v in os.environ.items()
                 if k in ('PATH', 'HOME', 'XDG_RUNTIME_DIR') or k.startswith('DOCKER_')}
        result = subprocess.run(['docker', 'compose', '-f', str(compose_file), '--env-file', str(env_file),
                                 'config', '--format', 'json'], capture_output=True, text=True, check=False, env=shell)
    if result.returncode != 0:
        raise AssertionError(f'docker compose config failed: {result.stderr.strip()}')
    return json.loads(result.stdout)


def members(document: dict, network: str) -> set[str]:
    return {name for name, service in document['services'].items() if network in (service.get('networks') or {})}
