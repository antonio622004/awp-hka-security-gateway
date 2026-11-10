# Python- und Testumgebung – Stand 2026-11-10

## Portalstandard übernommen

* `pyproject.toml`: Python mindestens 3.13; Testpakete unverändert in `dev`
  verschoben. Laufzeitabhängigkeiten und ihre Versionsvorgaben bleiben unverändert.
* `.python-version`: 3.14, passend zur bevorzugten CI-/Docker-Version des Portals.
* `Makefile`: `make setup` → `uv sync`; `make test` → `uv run pytest -q tests`.
* `.github/workflows/pruefung.yml`: Python 3.14, uv 0.11.0, `UV_LOCKED=1`,
  Setup, Ruff und vollständige Gatewaytests. Keine UI-/SDK-/Node.js-Schritte.
* Dockerfile: uv-Builder wie Portal-Trixie, Installation mit `--frozen`,
  getrennte Laufzeit- und Testumgebung, Python 3.14. Runtime ohne `dev` und uv;
  bestehender Benutzer 10001, Healthcheck, Ports und Serveroptionen bleiben.
  Testtarget enthält zusätzlich Quellen für die bestehenden Quellvergleichstests.

Keine Anwendung, Architektur, Sicherheitsprüfung oder Portaldatei wurde geändert.

## Noch nicht abgeschlossen: Lockdatei und Installation

`uv` ist lokal nicht installiert. Der Bezug von `uv==0.11.0` über pip ist gescheitert;
DNS für `pypi.org` und `files.pythonhosted.org` ist nicht verfügbar. Es gibt hier nur
System-Python 3.12.3, keinen einsatzfähigen Interpreter 3.14. Die früher vorbereitete
`.venv` ist leer und basiert noch auf 3.12.3. Sie ist kein bestandener Testaufbau.

Deshalb wurde **keine eigene `uv.lock` erzeugt**. Keine alternative Paketversion,
kein kopiertes Portal-Lockfile und kein manuelles Lockfile als Ersatz. Der neue
Dockerbuild verlangt `uv.lock`; CI verweigert deren automatische Änderung. Beide
bleiben ohne generierte Datei bewusst blockiert. Die Konfigurationsumstellung
ist vorbereitet, aber noch nicht als funktionierender Build abgenommen.

Sobald uv/Python und eine geeignete Paketquelle bereitstehen, im Gateway:

```sh
uv lock
make setup
make test
```

Die generierte eigene Lockdatei prüfen und versionieren. uv kann die alte
unpassende venv ersetzen; native Pakete nicht aus anderen Umgebungen kopieren.
Für spätere Abhängigkeitsänderungen `uv add` bzw. `uv add --dev` verwenden.

## Aktueller Prüfstand

* `uv lock`: nicht ausführbar, `uv: command not found`.
* `make setup`: Fehler 127, uv fehlt.
* `make test`: Fehler 127 vor pytest; keine Tests gesammelt oder ausgeführt.
* Ein vollständiger HTTP-/Gesamtlauf ist weiterhin offen. Es wurden in diesem
  Schritt keine alternativen Versionen oder gemischten Paketpfade eingesetzt.
* Statisch geprüft: TOML, Pythonvorgaben, YAML-Struktur, Makefile-Befehle und Ruff.
  Das ersetzt keine erfolgreiche uv-Auflösung, CI oder Dockerbuild.

## Historische Ursachen der vorherigen Testprobleme

System-Python hatte FastAPI, HTTPX, Redis, fakeredis und pytest nicht installiert;
`ensurepip` fehlte. Die Golden-Master-venv verweist auf einen nicht vorhandenen
Interpreter und enthält native CPython-3.14-Module, die nicht unter 3.12 verwendbar
sind. Das frühere Mischen reiner Pakete führte zusätzlich zu inkompatiblem
`typing_extensions`. Dieser Ansatz wird nicht zum neuen Setup übernommen.

Die vorher berichteten 38 erfolgreichen Komponenten-/Vergleichsprüfungen sind
historische Teilergebnisse und kein aktueller Gesamtlauf der neuen uv-Umgebung.
Offen bleiben insbesondere die FastAPI-HTTP-Tests für OIDC, Sessions, Registry,
Autorisierung, Assertions und App-Proxy. Keine VM-/Deploymentänderungen.
