# GitHub-Push-Vorbereitung – HKA-AWP

Prüfdatum: 2026-11-10. Dies ist eine lokale technische Prüfung, keine Pushfreigabe.
Durch den Assistenten wurden keine Commits, Pushes, Git-Initialisierung,
Remoteänderungen oder Branchwechsel durchgeführt. Vorhandene Änderungen wurden
nicht verworfen. Während der Prüfung erschien außerhalb dieser Git-Aktionen der
Portalcommit `6bd80d0`; er wurde weder verändert noch zurückgesetzt.

## A. Gesamtstatus

**Noch nicht bereit für eine bedingungslose Pushfreigabe; technisch weitgehend vorbereitet.**

Die integrierte Laufzeit ist durch automatisierte ASGI-Tests belegt. Für den
kontrollierten Push fehlen die Freigabe zum Umgang mit dem aktiven, bereits in
Git vorhandenen lokalen Client-Secret, Gateway-Git/Remote sowie
der vollständige manuelle Container-/Browsernachweis. Die JavaScript-SDK-Prüfung
und eine Starter-Selbstprüfung sind umgebungsbedingt noch nicht grün.

Das ist keine Feststellung eines fehlgeschlagenen echten Docker-Builds: Docker
konnte hier nicht gebaut oder gestartet werden. Ein früher gemeldeter lokaler
Benutzertest wird nicht als selbst durchgeführter vollständiger Test gezählt.

## B. Repository-Status

| Projekt | Lokaler Stand | Remote | Ungepushte Commits |
|---|---|---|---|
| Security Gateway | Kein Git-Repository; gesamtes Projekt vor Erstaufnahme prüfen | keiner | nicht anwendbar |
| Portal | `feature/gateway-portal-integration`, HEAD `6bd80d0`; abschließend sauber | `https://github.com/alexandru-tatar/awp-hka-intranet-portal.git` | **1** gegenüber vorhandenen Remote-Refs |
| SyncShare | `main`, HEAD `3fc5f42`; lokale Dokumentations-/Ignore-/Testkorrekturen | `https://github.com/alexandru-tatar/app-syncshare-test.git` | 0 gegenüber vorhandenen Remote-Refs |

Portal und App sind keine Shallow-Clones. Der Online-Stand konnte wegen
GitHub-DNS-Sperre nicht abgeglichen werden; `origin/main` ist der lokal bekannte
Stand. Das Portal hat keinen Upstream für den Featurebranch. Die Autorenidentität
war anfangs nicht verfügbar; die abschließende `git var GIT_AUTHOR_IDENT`-Prüfung
ist in Portal und App erfolgreich. Gateway-URL/Owner und Initialbranch müssen vom Team
bestätigt werden. Keine Repositorys oder Remotes wurden erfunden/angelegt.

Anfangs bestanden im Portal vorgemerkte und nicht vorgemerkte Dateien. Bei der
Schlussprüfung waren sie in dem inzwischen erschienenen Commit `6bd80d0`
enthalten (18 Dateien, 734 hinzugefügte/17 entfernte Zeilen); Arbeitsbaum und Index
sind jetzt sauber. Dieser Commit stammt nicht aus einer Aktion dieses Auftrags.
Vor weiteren Schritten nochmals Status/Log und Inhalt des Commits prüfen.

### Portal-Integration (jetzt im lokalen Commit `6bd80d0` gegenüber `474c4b6`)

- `src/portal/app.py`, `context.py`, `core/config.py`, `web/deps.py`:
  optionaler Gateway-Modus, Verifier/Benutzerkontext, keine zweite Portal-Session.
- `src/portal/auth/gateway.py`: öffentliche Gateway-Schlüssel, JWT-Prüfung.
- `src/portal/router/internal_registry_router.py`: Serviceauthentifizierung,
  lesende API und benutzerbezogene Portalentscheidung.
- `src/portal/router/nav_router.py`, `health_router.py`: Navigation und
  Bereitschaft ohne Portal-Sessionstore.
- `tests/test_gateway_flow.py`, `test_gateway_identity.py`,
  `test_internal_registry.py`: Integrations-/Sicherheitsnachweise.
- `extras/compose/vm/compose.registry.yml`, `nginx-portal.conf`: bereits vorher
  vorbereitete opt-in Registry-Vernetzung und öffentliche interne Pfadsperre.
  Diese sind nicht auf einer VM installiert worden.
- `Dockerfile.local`: lokale öffentliche Python-/uv-Basis, inzwischen committed.
- `README.md`, `docs/07-registry-und-apps.md`: Integration und lokale Container.
- `.gitignore`, `.dockerignore`: Korrekturen aus diesem Auftrag.

Keine Anwendungsdatei wurde in diesem Auftrag gelöscht. Das im früheren Umbau
entfernte kopierte Gateway-`app_service.py` existiert nicht mehr; es gibt dort
keine Git-Historie, aus der eine Dateilöschung gestaged werden könnte.

### Gateway für die Erstaufnahme

Zu prüfen/aufzunehmen: `src/`, `tests/`, `tools/`, `deployment/`, `docs/`,
`.github/`, `.python-version`, `.env.example`, `.gitignore`, `.dockerignore`,
`pyproject.toml`, `uv.lock`, `Makefile`, `Dockerfile`, `compose.yml`,
`compose.portal.yml`, `compose.registry.yml`, `README.md`.
Nicht aufnehmen: `.venv`, Caches, lokale Secrets/Schlüssel, `.env`, Laufzeitdaten.

Appänderungen dieses Auftrags: `.gitignore`, `.dockerignore`, `README.md`,
`tools/tests/starter/test_starter.py`. SDK, Anwendungslogik, Manifest, Dockerfile
und Lockfile der App sind unverändert.

## C. Änderungen dieses Auftrags

| Datei | Änderung / Begründung |
|---|---|
| Alle drei `.gitignore` | Lokale `.env.*`, Schlüssel/Keystores und Datenbanken ausschließen; `.env.example` erlauben. Portal zusätzlich Cache-/`.env`-Regeln. Bereits getrackte Dateien werden dadurch nicht entfernt. |
| Alle drei `.dockerignore` | Git-Historie, lokale Umgebungsdateien und Schlüssel/Datenbanken aus Build-Kontext ausschließen. Die kopierten Runtimequellen bleiben verfügbar. |
| Gateway `.env.example` | Nur Platzhalter für externe Pfade/Netzname und lokale nicht geheime URL-Einstellungen. |
| Gateway `docs/gateway-portal.md`, `README.md` | Frischer Clone, Netzermittlung, Clientfreigaben, Secret-Einrichtung, Status/Logs/Stop und Fehlerhilfe; Phase-1-Smoke vom Integrationstest unterscheiden. |
| Gateway `docs/push-readiness.md` | Dieser Bericht, Befunde, Prüfgrenzen und späterer Commit-/Pushplan. |
| Gateway `src/gateway/registry_client.py`, `app.py` | Ausschließlich veraltete Docstring-/Kommentartexte korrigiert; kein Verhalten geändert. |
| Portal `src/portal/core/config.py` | Fehlermeldung nennt den bereits vorhandenen Modus `gateway`. |
| App `README.md` | Tatsächliche SyncShare-Testfunktion statt leerem Golden-Master-Starter beschreiben. |
| App `tools/tests/starter/test_starter.py` | Vergleich mit JS-Starter nur im eigentlichen Python-Golden-Master ausführen. Eine echte App muss ihr angepasstes Manifest nicht identisch zum Starter halten. Sicherheitsprüfungen bleiben erhalten. |

Produktives Portal-`Dockerfile`, Runtime-Abhängigkeiten und alle drei Lockfiles
wurden nicht geändert. Keine zusätzliche Bibliothek und kein Versionsupgrade.
`npm ci` wurde versucht, scheiterte aber am Netzwerk; eventuell unvollständige
`node_modules` bleiben ignorierte lokale Artefakte. Startertests erzeugten eine
unvollständige ignorierte App-`.venv`; sie ist keine fertige Testumgebung.
Generierte Prüfberichte liegen unter ignoriertem `app-syncshare-test/build/`.

## D. Testergebnisse

| Prüfung | Ergebnis |
|---|---|
| Gateway `tests` | **81 bestanden, 14 Untertests bestanden**, 2 Warnungen |
| Portal `tests` | **351 bestanden, 1 übersprungen** (Docker/Gitleaks-Prüfung nicht möglich) |
| Portal Python-SDK | **33 bestanden** |
| Portal Kit-Kontrast | **22 Prüfungen bestanden** |
| SyncShare `tests` | **11 bestanden** |
| SyncShare Skill-Selbsttests | **120 bestanden** |
| SyncShare Starter-Selbsttests, letzter Lauf | **48 bestanden, 5 übersprungen, 1 umgebungsbedingt fehlgeschlagen** |
| Ruff Gateway | bestanden |
| Ruff Portal inkl. `sdk/python` | bestanden |
| Ruff App inkl. `tools`, Formatprüfung | bestanden |
| App SDK-Integritätsprüfung `platform_sdk.verify_tree` | bestanden |
| Direkte Ruff-Kanarienprüfung verbotener Import | bestanden (`TID251`) |
| `uv lock --check --offline`, alle drei Projekte | bestanden |
| Compose-Deploymentprüfungen | in Gatewaytests enthalten, bestanden; kein Dienststart |
| Git-Diff-/Whitespace-Prüfungen | bestanden; produktives Portal-Dockerfile unverändert |
| Portal JavaScript-SDK `npm test` | 2 Testdateien scheitern an fehlenden npm-Abhängigkeiten; kein Funktionsnachweis |
| `npm ci` für JS-SDK | Netzwerkfehler `ENOTFOUND registry.npmjs.org`; keine Ersatzversionen |
| Echte Docker-Builds/-Starts, Browser, realer Keycloak/Redis | nicht ausführbar (Docker-Daemonberechtigung fehlt) |
| Gitleaks-/Hadolint-Binärlauf | Werkzeuge lokal nicht vorhanden; kein erfolgreicher Lauf behauptet |

Der verbleibende Starterfehler stammt aus `uv run ruff` im App-eigenen Environment:
Ruff kann offline nicht installiert werden. Die gleiche Sicherheitsregel wurde
mit vorhandenem Ruff separat nachgewiesen, der ursprüngliche Selbsttest bleibt
aber ausdrücklich fehlgeschlagen. Übersprungen: freigegebener SDK-Vergleich mit
Ordner `../portal`, Dockerprüfung und drei für App-Repositories unpassende
Golden-Master-Gleichlaufprüfungen. Kein SDK-Schutz wurde deaktiviert.

Ein erster Sammellauf von App-/Skill-/Startertests scheiterte an kollidierenden
`conftest`-Imports. Getrennte Prozesse entsprechen dem vorhandenen Makefile.
Ein erster Starterlauf ohne den Sandbox-Runner wurde abgebrochen, weil normale
TestClient-Thread-Wakeups hier hängen. Spätere ASGI-Läufe nutzen den bestehenden
temporären AnyIO-Runner mit periodischem Selector-Wakeup. Er ersetzt weder
Anwendungslogik noch Sicherheitsprüfungen und gehört nicht ins Repository.

App und Python-SDK wurden mit den kompatiblen vorhandenen Python-3.14-Abhängigkeiten
im Portal-Environment geprüft, nicht mit einer vollständig installierten eigenen
App-Umgebung. CI/frischer Rechner muss regulär `uv sync --locked --group dev`
ausführen. Die Wrapperaufrufe geben einzelne bekannte Pytest/HTTPX-Warnungen aus.

## E. Architektur, Docker und Sicherheit

### Tatsächliche Aufteilung

```text
Browser → Gateway → Portal (UI)
Browser → Gateway → Portalentscheidung → Gateway → Micro-App
Gateway → Keycloak (Login) / Redis (Session)
```

Die Kurzform `Gateway → Portal → Micro-App` ist als Datenpfad ungenau: Das Portal
entscheidet, der Gateway spricht die App direkt an. Es gibt keine doppelte
Manifestrollenprüfung im Gateway und keine zweite Registry. Portal-/App-Tokens
bleiben getrennt; Adapter-Audience und `scp` bleiben im vorhandenen Vertrag.
Die App-SDK-Prüfung schützt auch statische App-Assets. `/healthz` der App sowie
minimaler Portal-`/readyz` sind bewusste interne Ausnahmen.

Gateway-Modus ersetzt keine vorhandene Dev-/OIDC-Konfiguration automatisch.
Adminformulare bleiben rollen-/CSRF-geschützt; lokale Demo ist ausdrücklich
read-only administriert. Keine neue Grants-/LDAP-/Refreshfunktion ergänzt.

### Dockerprüfung

- Lokal wählt `compose.portal.yml` ausschließlich `Dockerfile.local` im
  Portal-Buildkontext. VM/Produktion verwendet weiter das unveränderte DHI-Dockerfile.
- Lokal Builder und Runtime `python:3.14.3-slim-trixie`, uv 0.11.0; Pfad `/opt/app`
  identisch, nicht editierbare venv und gebautes Kit werden übernommen.
- Gateway nutzt ebenfalls Python 3.14/Trixie und uv 0.11.0; Test-App Python 3.14.3
  mit öffentlichem uv/Python-Builder. Kein Abhängigkeitswechsel nötig.
- Runtime als Nicht-root-Benutzer; read-only, tmpfs, `cap_drop=ALL` und
  `no-new-privileges` der lokalen Integration bleiben gesetzt.
- Nur Gateway veröffentlicht `127.0.0.1:18080:8080`. Kein Hostport für Portal,
  Test-App oder Gateway-Redis. Interne Ports: Portal 8000, Gateway/App 8080, Redis 6379.
- Portalnetz verbindet nur Gateway/Portal; Appnetz nur Gateway/Test-App;
  Sessionsnetz nur Gateway/Redis. Gateway zusätzlich im bestehenden IdP-Netz.
- SDK erreicht JWKS/Navigation über `http://gateway:8080`; `gateway` ist ausdrücklich
  als interner Host erlaubt. Portal/JWKS-DNS und Upstreamnamen passen.
- Startabhängigkeit Redis: Healthcheck; Portal: nur `service_started`.
  Ein kurzer 503 während Portalstart bleibt möglich. Gateway-Healthcheck prüft
  den Prozess, `/readyz` Redis; nicht die gesamte Plattform. App hat SDK-Healthcheck.
- Manifest wird read-only direkt aus der App gemountet, keine zweite Registry.
  Demo-Appstatus ist statisch; tatsächlicher Verbindungsfehler bleibt fail-closed.

### Secretprüfung

Eigene lokale, redigierte Musterprüfung: 54 Gatewaydateien, 248 Portaldateien und
75 Appdateien (letzte Prüfung einschließlich dieses Berichts). Zusätzlich alle lokal erreichbaren
Git-Objekte einschließlich Remote-Refs/Reflogs: **386 Portal-Blobs, 80 App-Blobs**.
Keine Gateway-Historie vorhanden. Virtuelle Environments, Git-Interna im
Dateibaum, Caches, node_modules und Build-Ausgaben wurden als Artefakte getrennt
behandelt. Keine vollständige Entwarnung/kein Gitleaks-Ersatz; Online-Refs unbekannt.

**Wesentlicher Befund:** Ein externer aktiver lokaler Client-Secretwert stimmt exakt
mit bereits versionierten Entwicklungsdaten überein, ohne ihn hier auszugeben:

- Portal `dev/keycloak/portal-client-secret:1`.
- Portal `extras/compose/keycloak/hka-realm.json:25`.
- Portal `docs/04-anmeldung.md:110`.

Auch in vorhandener Historie: u. a. Blobs `30a33f1117ec`, `0e52aecd180b`,
`43ad28e713c5`, `e7da3957cfa5`. Realmexport enthält sieben lokale Benutzer mit
bekannten Passwortfixtures; Compose enthält bekannte Bootstrap-Testzugangsdaten.
Diese Werte sind Entwicklungsfixtures und müssen entsprechend behandelt werden.
Die Übereinstimmung zeigt aber, dass der aktive lokale Clientwert **nicht als
vertraulich gelten kann**. Kein konkreter Missbrauch wird behauptet.

Vor Veröffentlichung/Betrieb mit Schutzbedarf: zuständige Person muss die
Verwendung bestätigen und den aktiven Clientwert rotieren, externe Datei und
alle betroffenen Clients koordinieren. Kein Realmreset. Fixtures ausschließlich
als bekannte isolierte Testkonfiguration freigeben. `.gitignore` repariert keine
bereits getrackten oder historischen Inhalte. Löschen allein macht den Wert nicht
wieder geheim. Falls ein echter Produktivwert betroffen ist: zusätzlich Widerruf,
Nutzungsprüfung und gemeinsam beschlossene Historienbereinigung; keine automatische
Historienumschreibung in diesem Auftrag.

Keine zusätzlichen tatsächlichen API-Tokens, privaten Schlüssel, Datenbanken oder
Docker-Credentials im untersuchten Kandidatenstand gefunden. Gatewaytestwerte
und das App-Secret-Skill-Beispiel sind erkennbare Test-/Dokumentationsliterale.
Private externe Signierschlüssel/Service-Token werden nicht versioniert oder im
Bericht ausgegeben. Repo-Ignores und Docker-Ignores verhindern ihre versehentliche
Neuaufnahme, soweit die Muster greifen; `git add -f` könnte sie trotzdem umgehen.

### Weitere bewusste Grenzen

Gemeinsame Browser-Origin ist nur für die vertrauenswürdige Test-App geeignet,
nicht für beliebigen KI-Code. Interne HTTP-Antworten vertrauen dem isolierten
Docker-Host/Netz; über fremde Netze TLS erforderlich. Rollen bleiben Login-Snapshot;
kein automatischer Gruppenrefresh/Backchannelwiderruf. Übernommene Proxygrenzen
(Location-Präfix/Connection-Header) und Session-Touch-/Logout-Race sind dokumentierte
Altgrenzen, hier nicht umgebaut. Kein Produktivfreigabenachweis.

## F. Offene Punkte nach Priorität

**Kritisch vor endgültiger Freigabe**

1. Aktiven bereits bekannten Client-Secretwert und Testfixture-Freigabe mit dem
   Verantwortlichen klären; notwendige Rotation außerhalb Git koordinieren.
2. Vollständigen lokalen Container-/Browserlauf einschließlich Logout und
   Ausfalltests abnehmen und Commitstände festhalten.
3. Gateway-Git/Remote/Owner und Initialbranch ausdrücklich bestätigen; keine
   automatische Einrichtung. Autorenidentität bei Erstaufnahme erneut prüfen.

**Wichtig vor Push/PR-Abnahme**

- JS-SDK nach `npm ci` und App-Starter nach vollständigem `uv sync` erneut prüfen.
- CI auf dem tatsächlichen neuen Branch ausführen; Gateway-CI enthält bisher
  keinen Gitleaks-Schritt. Historien-/Dateiscan mit dem vorgesehenen Scanner nachholen.
- Aktuelle Remote-Refs auf einem Rechner mit Netzwerk frisch abgleichen.
- Portal und Gateway gemeinsam freigeben: alter Portalstand hat keinen
  passenden Autorisierungsendpunkt. CI klont die Peers nicht automatisch;
  Cross-Repo-Test wird dort ohne Peers übersprungen.
- Neuen bereits vorhandenen Portalcommit `6bd80d0` vor Push vollständig prüfen; nicht ohne Freigabe umschreiben.
- Lizenz/Veröffentlichungsrechte im Team klären: keine Root-LICENSE in den drei
  Projekten vorhanden; keine Lizenz automatisch erfunden.

**Optional / später, vor echter Produktion teilweise zwingend**

- Eigene App-Origins und Cookie-/Sessionbetrieb für unvertrauenswürdige KI-Apps.
- TLS/Rate Limits, Rollenaktualisierung, administrativer Sessionwiderruf.
- Cross-Repo-CI mit festgelegten kompatiblen Refs; mehr Start-Readiness statt
  `service_started`; dynamischer App-Prober statt Demo-Status.
- Pflege historischer Phase-1-Dokumente; README zeigt bereits den aktuellen Einstieg.

## G. Commit- und Pushplan (nur Vorschlag, NICHT ausgeführt)

Nach expliziter Freigabe und Integrationstest, nicht vorher:

### Portal

Der ursprünglich geplante Split in `feat: integrate gateway identity and app
authorization`, `build: add local portal Dockerfile` und
`docs: document gateway portal integration` ist inzwischen durch den vorhandenen
lokalen Commit `6bd80d0` zusammengefasst. **Keinen zweiten identischen Commit
anlegen und diesen nicht ohne ausdrückliche Freigabe aufteilen/amendieren.**

```sh
cd ~/projects/awp/awp-hka-intranet-portal
git status --short --branch
git fetch origin
git log --oneline --decorate -5
git show --stat 6bd80d0
git diff 474c4b6..6bd80d0 --check
# Aktuelle Remoteänderungen prüfen, nicht automatisch resetten/mergen.
# Bestehenden vollständigen Commit nach manueller Abnahme/Freigabe veröffentlichen:
git push -u origin feature/gateway-portal-integration
```

Autorenidentität ist bei der Schlussprüfung auflösbar. Falls weitere Korrekturen
notwendig werden, eigene kleine Folgecommits mit geprüften expliziten Dateipfaden
verwenden. Ein Fetch ist kein automatischer Merge/Reset.

### Gateway

Es existiert keine Basis-Historie. Für die erste Veröffentlichung ist ein
konsistenter Initialcommit sinnvoller als eine erfundene Rekonstruktion der
Entwicklung: `feat: add standalone security gateway`. Build, Tests und Dokumente
gehören dabei zum ausführbaren Erststand. Spätere Änderungen getrennt committen.

```sh
cd ~/projects/awp/awp-hka-security-gateway
# Erst nach bestätigtem Owner, Initialbranch und leerem Zielrepository:
git init -b main
git config user.name 'TEAM_BESTAETIGTER_NAME'
git config user.email 'TEAM_BESTAETIGTE_COMMIT_EMAIL'
git remote add origin 'TEAM_BESTAETIGTE_GATEWAY_GIT_URL'
git add -- src tests tools deployment docs .github .python-version .env.example \
  .gitignore .dockerignore pyproject.toml uv.lock Makefile Dockerfile \
  compose.yml compose.portal.yml compose.registry.yml README.md
git diff --cached --check
git diff --cached --stat
# Vorgesehenen Secret-Scanner über Kandidatenstand ausführen, Fundstellen prüfen.
git commit -m 'feat: add standalone security gateway'
git push -u origin main
```

Kein GitHub-Repository wurde angelegt. Bei nicht leerem Remote **nicht** blind
initialisieren/force-pushen, sondern dessen Historie zuerst abgleichen. `main` ist
hier nur ein Vorschlag für einen leeren Erstimport, keine stillschweigende Teamregel.

### SyncShare

1. `test: limit starter parity checks to golden master` – nur korrigierter Testskope.
2. `chore: exclude local credentials from build contexts` – Ignoredateien.
3. `docs: describe SyncShare gateway integration` – README.

```sh
cd ~/projects/awp/app-syncshare-test
git fetch origin
git switch -c chore/prepare-gateway-integration
git add -- tools/tests/starter/test_starter.py
git diff --cached --check
git commit -m 'test: limit starter parity checks to golden master'
git add -- .gitignore .dockerignore
git commit -m 'chore: exclude local credentials from build contexts'
git add -- README.md
git commit -m 'docs: describe SyncShare gateway integration'
git push -u origin chore/prepare-gateway-integration
```

Diese Befehle sind ausdrücklich Zukunftsschritte und wurden hier nicht ausgeführt.
Keine Keys/Secrets als Commitargumente verwenden, keine Force-Pushes.

## H. Manuelle lokale Abnahme

1. Richtige drei Ordner/Refs, Secretdateien außerhalb Git, aktuellen Keycloak-Client
   und Callback/Logoutfreigaben prüfen. Keine echte Hochschulkennung erforderlich.
2. `compose.yml` + `compose.portal.yml`: `config --quiet`, `build --pull`, `up -d`.
3. `ps`, Logs, Healthchecks und laufende Netzmitgliedschaften prüfen; kein neuer
   Hostport für Portal/App/Redis. Alte unabhängig gestartete Dev-Portale beachten.
4. Browser ohne Cookie → Keycloak → Portal. Als `student` SyncShare sichtbar;
   Upload/Download, CSS/Navigation funktionieren. Als unpassende Rolle 403.
5. `/me` anonym 401; öffentliche `/internal/...` 404. Direkter Portal-/App-Hostport
   nicht erreichbar; Manipulationsheader dürfen keine Identität erzeugen.
6. Logout mit gültigem Formular erfolgreich; alte Session danach verweigert.
   Falsches CSRF/Origin abgelehnt, Sessionablauf nach konfigurierten fünf Minuten.
7. Portal- bzw. Rediscontainer nur im isolierten Test kontrolliert stoppen:
   kein Appzugriff bei Ausfall; keine alte Entscheidung aus Cache. Danach wieder starten.
8. Keine Token/Secretwerte in Screenshots, Logs oder Git. Testergebnis und verwendete
   Refs dokumentieren. Erst dann Commit-/Pushfreigabe erteilen.

Ausführliche Befehle und Fehlerhilfe: [gateway-portal.md](gateway-portal.md).
