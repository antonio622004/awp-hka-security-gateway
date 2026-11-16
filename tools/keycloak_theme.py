#!/usr/bin/env python3
"""Design-Kit des Keycloak-Login-Themes: versionierte Kopie unter `keycloak/theme-kit/`.

Die Kopie kommt aus dem Portal-Repository (`make keycloak-theme-release` dort, Ausgabe
`sdk/dist/keycloak-theme/`). Inhalt: `kit.css`, `fonts/` (mit `OFL.txt`), `VERSION`, `SHA256`.
Die Prüfsumme folgt demselben Verfahren wie das Portal-SDK (`platform_sdk.verify_tree.tree_hash`).

    python tools/keycloak_theme.py update <THEME_DIST>   Kopie prüfen und übernehmen
    python tools/keycloak_theme.py verify                 Kopie im Repository prüfen
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "keycloak" / "theme-kit"
SUM_FILE_NAME = "SHA256"
REQUIRED = ("kit.css", "VERSION", "fonts/OFL.txt")


def tree_hash(root: Path) -> str:
    """SHA-256 über die sortierte Liste (relativer Pfad, Inhalt) aller Dateien außer `SHA256`."""
    digest = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.name != SUM_FILE_NAME and "__pycache__" not in p.parts)
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return "sha256:" + digest.hexdigest()


def check(root: Path) -> str:
    """Prüft Vollständigkeit und Summe; gibt die Version zurück oder bricht mit einer Meldung ab."""
    missing = [name for name in (*REQUIRED, SUM_FILE_NAME) if not (root / name).is_file()]
    if missing:
        raise SystemExit(f"{root}: es fehlt {', '.join(missing)}")
    expected = (root / SUM_FILE_NAME).read_text(encoding="utf-8").strip()
    actual = tree_hash(root)
    if actual != expected:
        raise SystemExit(f"{root}: Prüfsumme passt nicht (erwartet {expected}, berechnet {actual})")
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def update(source: Path) -> str:
    version = check(source)
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(source, TARGET, ignore=shutil.ignore_patterns("__pycache__"))
    check(TARGET)
    return version


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    up = sub.add_parser("update")
    up.add_argument("source", type=Path, help="Ordner sdk/dist/keycloak-theme aus dem Portal-Repository")
    args = ap.parse_args(argv)
    if args.command == "update":
        version = update(args.source.resolve())
        print(f"keycloak/theme-kit ist jetzt Version {version} ({tree_hash(TARGET)})")
    else:
        print(f"keycloak/theme-kit Version {check(TARGET)} ist unverändert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
