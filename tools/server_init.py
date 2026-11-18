#!/usr/bin/env python3
"""Lokalen Gesamtstart vorbereiten (make server-init). Mehrfach aufrufbar, überschreibt nichts.

1. Secrets in server/.secrets/ (Ordner 0700, Dateien 0444), nur wenn sie fehlen:
   signing-key.pem (RSA 3072, PKCS#8), registry-service-token (zufällig), bwsync-credentials.key (Fernet),
   oidc-client-secret (Secret des Clients "portal" aus keycloak/hka-realm.json).
2. server/.env aus server/.env.example mit absoluten Pfaden und zufälligem Keycloak-Admin-Passwort,
   nur wenn server/.env fehlt.
3. Datenordner des Portals ../awp-hka-intranet-portal/.local/portal/{manifests,status,registry}; unter Linux
   gehören sie danach UID 10001 (Benutzer im Portal-Container), per Hilfscontainer, ohne sudo und ohne 0777.

Es werden keine Secret-Inhalte ausgegeben.
"""

# Normalerweise läuft das Skript unter Linux (DevContainer, WSL2). Die Windows-Anpassungen
# (Pfade mit "/", O_BINARY, Konsolen-Kodierung in main, kein chown außerhalb von Linux) sind eine
# bewusste Absicherung für den seltenen Fall, dass jemand das Skript direkt unter Windows aufruft.
# Nicht entfernen.

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server"
SECRETS = SERVER / ".secrets"
ENV_FILE = SERVER / ".env"
ENV_EXAMPLE = SERVER / ".env.example"
REALM = ROOT / "keycloak" / "hka-realm.json"
PORTAL = ROOT.parent / "awp-hka-intranet-portal"
PORTAL_DATA = PORTAL / ".local" / "portal"
PORTAL_SUBDIRS = ("manifests", "status", "registry")
CONTAINER_UID = 10001
HELPER_IMAGE = "redis:8-alpine"  # wird für den Stack ohnehin gebraucht; hat chown


def write_new(path: Path, data: bytes, mode: int) -> bool:
    """Datei neu anlegen. Gibt False zurück, wenn sie schon existiert (dann bleibt sie unberührt)."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), mode)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.chmod(path, mode)
    return True


def signing_key() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def oidc_client_secret() -> bytes:
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    for client in realm.get("clients", []):
        if client.get("clientId") == "portal" and client.get("secret"):
            return client["secret"].encode()
    raise SystemExit(f"{REALM.relative_to(ROOT)}: Client \"portal\" ohne Secret")


# Datei in server/.secrets/ -> Erzeuger (nur aufgerufen, wenn die Datei fehlt)
SECRET_FILES = {
    "signing-key.pem": signing_key,
    "registry-service-token": lambda: secrets.token_urlsafe(32).encode(),
    "bwsync-credentials.key": lambda: base64.urlsafe_b64encode(os.urandom(32)),
    "oidc-client-secret": oidc_client_secret,
}


def create_secrets() -> list[str]:
    SECRETS.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(SECRETS, 0o700)
    report = []
    for name, make in SECRET_FILES.items():
        path = SECRETS / name
        created = not path.exists() and write_new(path, make(), 0o444)
        report.append(f"  {'neu      ' if created else 'vorhanden'}  server/.secrets/{name}")
    return report


def env_values() -> dict[str, str]:
    return {
        "GW_ROLES_SOURCE": (PORTAL / "dev" / "roles.yml").as_posix(),
        "GW_OIDC_CLIENT_SECRET_SOURCE": (SECRETS / "oidc-client-secret").as_posix(),
        "GW_SIGNING_KEY_SOURCE": (SECRETS / "signing-key.pem").as_posix(),
        "HKA_REGISTRY_SERVICE_TOKEN_SOURCE": (SECRETS / "registry-service-token").as_posix(),
        "BWSYNC_CREDENTIALS_KEY_SOURCE": (SECRETS / "bwsync-credentials.key").as_posix(),
        "KC_BOOTSTRAP_ADMIN_PASSWORD": secrets.token_urlsafe(24),
    }


def create_env() -> list[str]:
    values = env_values()
    lines = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#") and not value and key in values:
            line = f"{key}={values.pop(key)}"
        lines.append(line)
    if values:
        raise SystemExit(f"server/.env.example: es fehlen die Schlüssel {', '.join(sorted(values))}")
    text = "\n".join(lines) + "\n"
    created = write_new(ENV_FILE, text.encode("utf-8"), 0o600)
    return [f"  {'neu      ' if created else 'vorhanden'}  server/.env" + ("" if created else " (unverändert)")]


def prepare_portal_dirs() -> list[str]:
    if not PORTAL.is_dir():
        raise SystemExit(f"Portal-Repository fehlt: {PORTAL} (muss neben diesem Repository liegen)")
    if not (PORTAL / "dev" / "roles.yml").is_file():
        raise SystemExit(f"{PORTAL / 'dev' / 'roles.yml'} fehlt")
    report = []
    for sub in PORTAL_SUBDIRS:
        path = PORTAL_DATA / sub
        report.append(f"  {'vorhanden' if path.is_dir() else 'neu      '}  {path.relative_to(PORTAL.parent).as_posix()}/")
        path.mkdir(parents=True, exist_ok=True)
    if not sys.platform.startswith("linux"):
        # Docker Desktop (macOS, Windows) bildet Besitzer bei Bind-Mounts selbst ab: kein chown nötig.
        report.append("  Besitzer: kein chown nötig (Docker Desktop)")
        return report
    pending = [sub for sub in PORTAL_SUBDIRS if (PORTAL_DATA / sub).stat().st_uid != CONTAINER_UID]
    if not pending:
        report.append(f"  Besitzer: schon UID {CONTAINER_UID}")
        return report
    if shutil.which("docker") is None:
        raise SystemExit("docker fehlt: die Portal-Ordner müssen UID 10001 gehören (chown per Hilfscontainer)")
    subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--user", "0:0", "--entrypoint", "chown",
         "-v", f"{PORTAL_DATA}:/portal", HELPER_IMAGE,
         "-R", f"{CONTAINER_UID}:{CONTAINER_UID}", *(f"/portal/{sub}" for sub in pending)],
        check=True,
    )
    report.append(f"  Besitzer: UID {CONTAINER_UID} gesetzt für {', '.join(pending)} (Hilfscontainer {HELPER_IMAGE})")
    return report


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="backslashreplace")
    print("Secrets (Inhalte werden nicht angezeigt):")
    print("\n".join(create_secrets()))
    print("Umgebung:")
    print("\n".join(create_env()))
    print("Portal-Ordner:")
    print("\n".join(prepare_portal_dirs()))
    print("Fertig. Start: make server-up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
