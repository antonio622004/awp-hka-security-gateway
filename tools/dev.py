#!/usr/bin/env python3
"""Gateway/Redis stack reusing existing Keycloak. Only a signing key is generated.

Requires only Python stdlib, openssl and Docker Compose on the host.
"""
import argparse
import os
from pathlib import Path
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def prepare(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if directory.is_symlink() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError("Secret directory must be owned by you with mode 0700, without symlink")
    key = directory / "signing-key.pem"
    if not key.exists():
        # OpenSSL receives no secret input, and writes only to this private directory.
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072",
                        "-out", str(key)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if key.is_symlink() or not key.is_file():
        raise RuntimeError("Unexpected signing key entry")
    # Only this generated file is managed; never change existing IdP secrets.
    key.chmod(0o444)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "up", "down", "logs", "config", "test"])
    args = parser.parse_args()
    if args.command == "test":
        subprocess.run(["docker", "build", "--target", "test", "-t", "hka-security-gateway-tests:local", str(ROOT)], check=True)
        subprocess.run(["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp",
                        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                        "hka-security-gateway-tests:local"], check=True)
        return
    directory = Path(os.environ.get("GW_LOCAL_DIR", str(Path(tempfile.gettempdir()) / f"hka-gateway-{os.getuid()}")))
    if ROOT == directory.resolve() or ROOT in directory.resolve().parents:
        parser.error("GW_LOCAL_DIR must be outside the repository")
    if args.command in ("init", "up", "config"):
        prepare(directory)
    if args.command == "init":
        print(f"Signing key prepared in {directory}; no IdP credentials generated or changed.")
        return
    if args.command in ("up", "config"):
        if not os.environ.get("GW_KEYCLOAK_NETWORK"):
            parser.error("GW_KEYCLOAK_NETWORK must identify the existing Keycloak network")
        secret = Path(os.environ.get("GW_OIDC_CLIENT_SECRET_FILE", ""))
        if not secret.is_absolute() or not secret.is_file():
            parser.error("GW_OIDC_CLIENT_SECRET_FILE must be an existing absolute external file path")
        if ROOT == secret.resolve() or ROOT in secret.resolve().parents:
            parser.error("OIDC secrets must remain outside this repository")
        print("Using existing Keycloak: no realm import/reset. Confirm the client permits this gateway's callback/logout URLs.")
    options = {"up": ["up", "--build", "-d"], "down": ["down"], "logs": ["logs", "--tail", "100"],
               "config": ["config", "--quiet"]}
    env = {**os.environ, "GW_LOCAL_DIR": str(directory.resolve())}
    subprocess.run(["docker", "compose", "-p", "hka-security-gateway-phase1", "-f", str(ROOT / "compose.yml"),
                    *options[args.command]], env=env, check=True)


if __name__ == "__main__":
    main()
