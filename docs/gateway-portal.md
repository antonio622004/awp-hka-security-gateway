# Gateway–Portal-Integration

## Verbindlicher Ablauf

- Browser → Gateway-Session in Redis → frische Portal-Assertion → Portal.
- App-Request → Gateway-Session → Portalentscheidung → separate App-Assertion → App.
- Kein Assertion-Cache, standardmäßig 60 Sekunden Gültigkeit.
- Portal bleibt einzige Registry und entscheidet mit seinem bestehenden
  `AppService.find_authorized()`. Die kopierte Gateway-Klasse wurde entfernt.
- OIDC, PKCE, Redis-TTL, Logout und App-Assertion-Vertrag bleiben erhalten.
- `GET /internal/apps/{slug}/access` bleibt als geschützte lesende Schnittstelle
  erhalten, wird vom Gateway aber nicht mehr verwendet. Alte Gateway-/Portalimages
  mit dem jeweils anderen API-Vertrag sind nicht kompatibel; Fehler sperren Zugriff.

## Portal-Modus und Schlüssel

`auth_mode: gateway` mit Abschnitt `gateway` (`issuer`, `jwks_url`, `public_url`,
optional `audience`, standardmäßig `hka-portal-ui`). Keine Portal-OIDC-, Redis- oder
Signaturschlüsselkonfiguration in diesem Modus. Ein externes
`PORTAL_REGISTRY_SERVICE_TOKEN_FILE` ist erforderlich.

Das Portal erzeugt in diesem Modus keinen Sessionstore, keinen Login-Service,
keinen App-Proxy und keinen privaten Signierschlüssel. Bestehende `dev`-/`oidc`-
Modi bleiben erhalten. Seiten, API und Kit-Assets verlangen eine Assertion;
`/readyz` ist als minimaler interner Prozesscheck ausgenommen. Interne APIs
verlangen ihre eigene Serviceauthentifizierung. Portal-App- und Login-Routen
sind im Gateway-Modus nicht registriert. Logout bleibt beim Gateway.

Portal-JWT: `iss`, `aud=hka-portal-ui`, `sub`, `name`, `roles`, `iat`, `exp`,
`jti`, `v=1`, `token_use=portal-ui`, zusätzlich `csrf` aus der Gateway-Session.
RS256, bekannte `kid`, vertrauenswürdig konfigurierte JWKS-URL, gültige Zeiten,
Pflichtclaims und Zweck werden geprüft. Nur öffentliche Schlüssel werden geladen,
maximal 64 KiB, kein Redirect/Umgebungsproxy, zweisekündiger HTTP-Timeout.
JWKS-Cache 300 Sekunden; unbekannte Schlüssel werden frühestens nach zwei Sekunden
erneut angefragt. Ohne gültigen Schlüssel keine Annahme. Schlüsselrotation:
neuen Schlüssel vor Verwendung veröffentlichen, alte Schlüssel mindestens bis
zum Ablauf ausgegebener Assertions verfügbar halten. Keine Browser-Tokenausgabe.

App-JWT unverändert: eigene App-Audience plus `portal` für SDK-Navigation,
gegebenenfalls `adapters`, dazu `azp` und `scp`. Diese App-Tokens dürfen nur `/nav`
als Portal-Navigationskontext aufrufen, niemals Portal-Seiten oder die interne
Autorisierungs-API. `/nav` am Gateway prüft das App-Token und reicht dessen
Authorization ausschließlich für diesen SDK-Aufruf weiter; der allgemeine Proxy
entfernt weiterhin alle eingehenden Authorization-Header.

## Entscheidungsvertrag

`POST /internal/apps/{slug}/authorize`

- `Authorization: Bearer <separates Service-Token>` und
  `X-Portal-Assertion: <frischer Portal-Benutzerkontext>` erforderlich.
- Erlaubt: 200 `{"slug":"…","allowed":true,"adapters":[…]}`.
- Verweigert: 403 `{"slug":"…","allowed":false,"reason":"forbidden"}`.
- Unbekannt/nicht geroutet: 404, gleicher Body mit `reason=not_found`.
- Nicht verfügbar: 503, gleicher Body mit `reason=unavailable`.
- Ungültige Serviceanmeldung oder Assertion: 401 mit eigener Fehlerkennung.
- Gateway akzeptiert ausschließlich den exakt validierten Vertrag; keine
  Manifestrollenprüfung, keine alten Entscheidungen und kein Redirect-Following.
  Technische Fehler/ungültige Antworten führen zu 503 ohne App-Aufruf.
- Metadaten kommen aus demselben Snapshot/AppDTO wie die Zugriffsentscheidung.

Anonyme App-Anfragen beginnen jetzt vor der Entscheidungsabfrage die Anmeldung.
Damit wird für anonyme Benutzer nicht mehr zuerst ein eventuell unbekannter
App-Slug durch die Registry aufgelöst. Angemeldete Benutzer erhalten die
bestehenden 403-/404-/503-Ergebnisse.

## CSRF und bestehende Administration

Das Portal verwendet einen unveränderlichen `GatewayUser`, keine künstliche
Session mit Session-ID. Dessen CSRF-Wert ist der zufällige Wert der echten
Gateway-Session und wird nur über die signierte interne Assertion übertragen.
Vorhandene Adminformulare rendern ihn weiter; `check_csrf()` und Adminrollenprüfung
bleiben unverändert wirksam. Bei jedem Formular-POST muss er zur aktuellen Session
passen. Gateway und Portal prüfen bei schreibenden Portalrequests zusätzlich die
exakte öffentliche Origin; fehlende/fremde Origin wird abgelehnt. Der Gateway setzt
für weitergeleitete Seiten `Referrer-Policy: same-origin`, damit Browserformulare
einen prüfbaren Origin senden. Auth-Callbackseiten behalten `no-referrer`.

Die vorhandenen Adminfunktionen bleiben rollen- und CSRF-geschützt. Individuelle
Grants im Portal werden nicht mit Gateway-Sessionrollen synchronisiert; eine solche
Synchronisierung wurde nicht ergänzt. Vorhandene Grants-Administration verändert
daher keine laufende Gateway-Identität. Die lokale Integration konfiguriert die
Verwaltung ausdrücklich lesend (`admin_write: false`), ohne Handler zu entfernen.

## Lokal mit der gelieferten Test-App starten

Voraussetzungen: Docker/Compose, alle drei Nachbarordner (`awp-hka-security-gateway`,
`awp-hka-intranet-portal`, `app-syncshare-test`), vorhandener erreichbarer Keycloak-
Container im Realm `hka`. Keine neue Keycloak-Instanz und kein Realmimport.

Im Gateway-Verzeichnis:

```sh
export GW_LOCAL_DIR="$HOME/.local/state/hka-gateway"
export GW_KEYCLOAK_NETWORK='<Name des bestehenden Keycloak-Docker-Netzes>'
export GW_OIDC_CLIENT_SECRET_FILE='<absoluter externer Pfad zum bestehenden Client-Secret>'
export HKA_REGISTRY_SERVICE_TOKEN_FILE="$GW_LOCAL_DIR/registry-service-token"
python3 tools/dev.py init
# Einmalig ein separates zufälliges Service-Token außerhalb des Repositorys erzeugen:
python3 - <<'PY'
import os, secrets
from pathlib import Path
p = Path(os.environ['HKA_REGISTRY_SERVICE_TOKEN_FILE'])
with p.open('x') as f:
    f.write(secrets.token_urlsafe(32))
p.chmod(0o444)
PY
docker compose -f compose.yml -f compose.portal.yml config --quiet
docker compose -f compose.yml -f compose.portal.yml up --build -d
```

Secretdatei nur einmal erzeugen, nicht bei jedem Start überschreiben. Das externe
Verzeichnis wird vom vorhandenen Werkzeug mit Modus 0700 geprüft. Die einzelne
Datei wird read-only in genau Portal/Gateway gemountet. Keine Secrets in Git.

Browser: **http://localhost:18080/** → Keycloak → Portal → „SyncShare“.
Für die App muss das Keycloak-Attribut `eduPersonAffiliation=student` ins ID-Token
aufgenommen werden (bestehendes `roles.yml`). Der vorhandene Client `portal` muss
`http://localhost:18080/oidc/callback` und den Logout-Rücksprung
`http://localhost:18080/` erlauben. Der Export allein beweist diese Freigaben nicht;
keine laufende Realmkonfiguration wurde geändert.

`deployment/portal.yml` und der SDK-Issuer sind bewusst auf diesen lokalen Origin
festgelegt. Für einen anderen Origin müssen Gateway, Portal-Konfiguration,
App-Issuer und OIDC-Redirects konsistent angepasst werden. HTTP ist hier eine lokale
Entwicklungsannahme, kein produktiver TLS-Ersatz.

Die App bleibt unverändert. Sie nutzt das echte SDK, den vollständigen Basispfad
`/apps/syncshare-test`, Gateway-JWKS und `/nav`. Uploadlimit der App: 2 MiB, Dateien
benutzerbezogen im RAM, keine echte bwSync&Share-Verbindung. Das Demo-Manifest wird
direkt aus dem Test-App-Verzeichnis read-only in die einzige Portal-Registry
gemountet. Der separate Demo-Status ist statisch `healthy`; tatsächliche
Verbindungsfehler führen trotzdem zu 503. Kein produktiver Prober wird vorgetäuscht.

## Netz und Betrieb

Nur Gateway-Port 18080 wird an Loopback veröffentlicht. Portal und App haben keine
Hostports. Internes Netz `portal`: ausschließlich Gateway/Portal; internes Netz
`apps`: Gateway/Test-App. App erreicht Portal oder Redis nicht direkt. SDK-Prüfung
verhindert zudem App-Zugriffe ohne gültiges App-Token. Gateway blockiert `/internal`
und Unterpfade öffentlich. Die neue Compose-Ergänzung ist separat; bestehende
Portal-/VM-Compose-Dateien werden hierfür nicht umgebaut.

Interne HTTP-Kommunikation setzt einen vertrauenswürdigen Docker-Host und geprüfte
Netzmitgliedschaft voraus. Service-Token authentifiziert den Aufrufer, JWT den
Benutzer. Es authentifiziert keine HTTP-Antwort kryptografisch: über Hostgrenzen
oder nicht vertrauenswürdige Netze ist serverauthentifiziertes TLS erforderlich.
`deployment/nginx-gateway.conf` ist ein nicht installierter Routingausschnitt für
den späteren HTTPS-Einstieg. Keycloak-/TLS-Konfiguration bleibt separat.

**Browser-Isolation bleibt offen:** Portal und Test-App liegen in dieser lokalen
Demo auf derselben Origin. Das ist keine Sicherheitsgrenze gegenüber bösartigem
App-JavaScript; insbesondere können gleich-originige Apps Portal-Seiten/CSRF-Werte
lesen. Daher nur mit vertrauenswürdiger Test-App verwenden. Eigene App-Origins sind
vor dem Betrieb unvertrauenswürdiger KI-Apps weiterhin erforderlich. Diese Aufgabe
führt kein neues Domain-/Cookie-Bootstrap-Konzept ein.

## Nachweise und Grenzen

- Gatewaytests: Entscheidungsvertrag, Header/Cookie-Filter, Fail-Closed,
  Session/OIDC/Logout, App-/Adapter-Assertions und Portalforwarding.
- Portaltests: Assertionprüfung, eigene Sessions abgeschaltet, Rollen/Manifest,
  Admin-CSRF, App-Token nur für Navigation, ungültige Signaturen/Audience/Ablauf.
- `Portal tests/test_gateway_flow.py`: tatsächliche drei ASGI-Anwendungen inklusive
  Test-App-SDK, JWKS, Navigation, Assets, Upload/Download, Verweigerung und CSRF.
  Erfordert den benachbarten Gateway und die Test-App; sonst expliziter Skip.
- Composekonfiguration wird ohne Dienststart geprüft. Kein echter externer Upload.
- Sandbox-Testläufe verwenden den bereits vorhandenen temporären AnyIO-Testrunner
  mit periodischem Eventloop-Wakeup, weil Thread-Wakeup-Sockets eingeschränkt sind.
  Anwendung und Sicherheitsprüfungen werden dadurch nicht ersetzt.
- Echte Keycloak-/Redis-/Docker-/Browser-/VM-Tests sind separat notwendig. Docker-
  Daemonzugriff ist in der aktuellen Arbeitsumgebung verweigert.

### Ergebnis des aktuellen Durchlaufs

81 Gatewaytests plus 14 Untertests erfolgreich. 351 Portaltests erfolgreich,
1 bestehender Test übersprungen. Ruff für beide Quellcode-/Testsammlungen sowie
Compose-Konfigurationsprüfung erfolgreich. Keine Abhängigkeiten oder Lockfiles
mussten geändert werden. Test-App, Adapter und Golden Masters unverändert.

Noch manuell: Images bauen, vorhandene Keycloak-Clientfreigaben prüfen, Login im Browser,
Portal-/Appdarstellung und Upload/Download, Logout, Sessionablauf und Ausfall
eines echten Redis-/Portalcontainers. Vor Veröffentlichung zusätzlich die
fehlenden Portal-/App-Portfreigaben und Netzmitgliedschaften im laufenden Docker
prüfen. Es wurde kein Container neu gestartet oder auf der VM ausgerollt.

## Öffentliche Basisimages für die lokale Entwicklung

`compose.portal.yml` baut das Portal mit `Dockerfile.local`: öffentliches
`python:3.14.3-slim-trixie` für Builder und Laufzeit, uv 0.11.0 aus dem öffentlichen
Astral-Image. Kein DHI-Zugriff und kein Docker-Login erforderlich. Das vorhandene
produktive `Dockerfile` sowie die VM-/Produktionskonfiguration bleiben unverändert.
Lockfile, gebaute Kit-Dateien, nicht editierbare Installation und Entrypoint bleiben
wie bisher. Der lokale Laufzeitcontainer verwendet einen eigenen Nicht-root-Benutzer
(UID 10001); read-only, Capability-Drop, Secret-Mounts und Netzwerkisolation der
Compose-Konfiguration bleiben erhalten. Das öffentliche Image ist kein DHI-Image.

Nach Setzen der bereits beschriebenen Umgebungsvariablen/Secretdateien:

```sh
cd ~/projects/awp/awp-hka-security-gateway
docker compose -f compose.yml -f compose.portal.yml build --pull
docker compose -f compose.yml -f compose.portal.yml up -d
```

Bestehender Keycloak wird nicht neu gebaut oder zurückgesetzt. Öffentliches
Herunterladen der Images und der gesperrten Python-Abhängigkeiten benötigt
Netzwerkzugriff. Ein tatsächlicher Docker-Build bleibt in der Arbeitsumgebung
wegen fehlender Docker-Daemonberechtigung ungeprüft.

## Reproduzierbarer Team-Test nach frischem Clone

Benötigte Verzeichnisstruktur (Gateway-URL erst nach Teamfreigabe bekannt):

```text
~/projects/awp/
├── awp-hka-security-gateway/
├── awp-hka-intranet-portal/
└── app-syncshare-test/
```

Portal muss den Integrationsstand mit `auth_mode: gateway` enthalten; das bisherige
`main` ohne diese Änderungen reicht nicht. Test-App-Referenz der Prüfung:
`3fc5f42`; Portal-Integrationsstand bei der Schlussprüfung: `6bd80d0`
(auf Basis von `474c4b6`).
Bei gemeinsamer Freigabe die tatsächlich gepushten Commit-IDs aller drei Projekte
festhalten. Kein unbestätigtes Gateway-Remote erraten.

Voraussetzungen: Docker mit Compose v2/BuildKit, Internetzugang für öffentliche
Images/Pythonpakete, Python 3.13+ (bevorzugt 3.14) und OpenSSL für den Schlüsselhelfer.
Host-uv ist für einen reinen Dockerstart nicht erforderlich; für lokale Tests
`uv sync --locked --group dev` je Projekt verwenden.

Vorhandenen Keycloak ermitteln, ohne ihn neu anzulegen oder zu ersetzen:

```sh
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
export KEYCLOAK_CONTAINER='replace-with-existing-container-name'
docker inspect "$KEYCLOAK_CONTAINER" \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}'
export GW_KEYCLOAK_NETWORK='replace-with-verified-existing-network-name'
```

Bei mehreren Netzen dasjenige mit Alias `keycloak` wählen. Container muss laufen
und lokal auf 8180 erreichbar sein. Nur einen vorhandenen gestoppten Container
gezielt starten; vorhandenen Realm nicht neu importieren oder zurücksetzen.
Eine frische lokale Instanz ist eine getrennte Betreiberentscheidung anhand der
Portal-Keycloak-Compose-Datei, keine Voraussetzung zum Ersetzen einer bestehenden.

Unter Realm `hka` / Client `portal` die bestehenden Einstellungen beibehalten und
folgende zusätzlichen Freigaben prüfen:

- Valid Redirect URI: `http://localhost:18080/oidc/callback`.
- Valid Post Logout Redirect URI: `http://localhost:18080/`.
- Client-Secret stammt aus der aktuellen Clientkonfiguration, nicht ungeprüft aus
  der versionierten Entwicklungsfixture. Diese enthält bekannte Testzugangsdaten.
- `eduPersonAffiliation=student` muss als ID-Token-Claim vorhanden sein, damit die
  Test-App angeboten und freigegeben wird. Kein LDAP erforderlich.

Im Gateway-Verzeichnis zusätzlich zu den oben beschriebenen externen Pfaden:

```sh
export GW_PUBLIC_URL=http://localhost:18080
export GW_OIDC_ISSUER=http://localhost:8180/realms/hka
export GW_OIDC_DISCOVERY_URL=http://keycloak:8080/realms/hka/.well-known/openid-configuration
export GW_OIDC_CLIENT_ID=portal
export GW_COOKIE_SECURE=false
```

`.env.example` enthält ausschließlich Pfad-/Netzplatzhalter. Optional nach `.env`
kopieren und nur die Pfade/Netznamen anpassen. Secrets bleiben externe Dateien;
Compose liest `.env` automatisch, der Python-Schlüsselhelfer dagegen nicht. Bei
Verwendung des Helfers die benötigten Pfade deshalb zusätzlich exportieren.
Shell-Variablen haben gegenüber `.env` Vorrang. Keine komplette `.env` aus fremder
Quelle mit `source` ausführen.

Falls die externe Client-Secretdatei noch fehlt: im eigenen Bash-Terminal das
aktuelle Secret verdeckt eingeben (nach `python3 tools/dev.py init`):

```bash
if [ ! -f "$GW_OIDC_CLIENT_SECRET_FILE" ]; then
  read -r -s -p 'Aktuelles Keycloak Client Secret: ' HKA_CLIENT_SECRET
  echo
  (umask 077; printf '%s' "$HKA_CLIENT_SECRET" > "$GW_OIDC_CLIENT_SECRET_FILE")
  unset HKA_CLIENT_SECRET
fi
chmod 444 "$GW_OIDC_CLIENT_SECRET_FILE"
```

Alle Secretdateien liegen im privaten externen Verzeichnis, im vorliegenden
Setup `~/.local/state/hka-gateway/` (0700). Leserechte 0444 der einzelnen gemounteten
Dateien sind für Containerbenutzer erforderlich; das Elternverzeichnis bleibt
für andere Hostbenutzer gesperrt. Dateien nicht überschreiben oder in Git aufnehmen.

Konfiguration prüfen, bauen und starten:

```sh
docker compose -f compose.yml -f compose.portal.yml config --quiet
docker compose -f compose.yml -f compose.portal.yml build --pull
docker compose -f compose.yml -f compose.portal.yml up -d
docker compose -f compose.yml -f compose.portal.yml ps
docker compose -f compose.yml -f compose.portal.yml \
  logs --tail=100 gateway portal app-syncshare-test gateway-redis
```

Im Browser `http://localhost:18080/` öffnen (nicht `127.0.0.1` und nicht Portalport
8000). Login, Portal, SyncShare, Upload/Download und Logout testen. `/me` ohne
Session muss 401 liefern; `/internal/apps/syncshare-test/access` am Gateway 404.
Die neuen Portal-/Appdienste haben keine veröffentlichten Hostports. Zusätzlich
prüfen, ob noch ein unabhängig gestartetes altes Dev-Portal einen Port veröffentlicht;
dies gehört nicht zum abgeschotteten Integrationsstack.

Beenden (Keycloak bleibt bestehen; Testdateien im App-RAM gehen verloren):

```sh
docker compose -f compose.yml -f compose.portal.yml down
```

### Häufige Fehler

| Fehler | Prüfen / beheben |
|---|---|
| DHI 401 | Lokalen Stack mit `compose.portal.yml` bauen; er wählt `Dockerfile.local`. Produktions-Dockerfile nicht ändern. |
| Fehlende Composevariable | Externe Pfade und verifizierten Keycloak-Netznamen exportieren oder `.env` mit Pfaden verwenden. |
| Keycloak invalid redirect URI | Exakten Gateway-Callback im bestehenden Client freigeben. |
| Keycloak invalid client | Aktuelles externes Client-Secret und Client-ID prüfen; nicht den bekannten Fixturewert übernehmen. |
| Discovery/Token nicht erreichbar | Netzalias `keycloak`, Containerstatus und internen Discoverypfad prüfen; VM-`/auth`-Pfad nicht mit lokalem Realm verwechseln. |
| Portal 401 / Gateway 503 | Issuer inklusive abschließendem Slash, Audience, Uhrzeit, JWKS-Erreichbarkeit und gemeinsames Service-Token prüfen. Keine Token/Secrets in Logs posten. |
| App fehlt / 403 | Benutzerattribut und resultierende Rolle `student`, Manifest und Portalentscheidung prüfen. |
| POST 403 | Exakt `http://localhost:18080` verwenden; Origin-/CSRF-Prüfungen nicht abschalten. |
| Docker permission denied | Docker-Daemonzugriff des lokalen Benutzers klären. |
| Netzwerk-/DNS-Fehler beim Build | Registry-/Paketquellenzugang prüfen; keine alternativen Dependency-Versionen einsetzen. |

`tools/smoke.py` prüft nur den separaten Gateway-Demomodus mit `/demo` und ist
nicht der Gesamttest für `compose.portal.yml` (dort ist die Demo ausgeschaltet).
Der vollständige Gruppentest erfolgt mit Browser bzw. `test_gateway_flow.py`.

Für Python-Tests auf der App `tests`, `tools/tests/skills` und
`tools/tests/starter` wie im Makefile in getrennten pytest-Prozessen ausführen;
eine gemeinsame Sammlung kollidiert mit den vorhandenen `conftest`-Imports.
