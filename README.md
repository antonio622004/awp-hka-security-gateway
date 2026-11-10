# HKA Security-Gateway

**Aktueller gemeinsamer Einstieg:** Für den vollständigen lokalen Stack zuerst
[Gateway–Portal-Startanleitung](docs/gateway-portal.md) verwenden. Die unten
beschriebene Phase-1-Demo ist nur ein unabhängiger Testmodus.

**Gateway–Portal-Integration:** [Vertrag, CSRF, lokale Test-App und Startanleitung](docs/gateway-portal.md).
Mit `GW_PORTAL_UPSTREAM` startet `/` ohne Session automatisch OIDC und leitet nach
Anmeldung mit einer frischen Portal-Assertion an das Portal weiter. Das Portal
muss dafür ausdrücklich `auth_mode: gateway` verwenden. Der optionale lokale
Stack `compose.portal.yml` verbindet das aktuelle Portal und `app-syncshare-test`.
Ohne Portal-Upstream bleibt der isolierte Demo-Modus verfügbar.

**Proxyintegration (Entscheidung B):** [Korrekturen, App-Routen und Tests](docs/proxy-decision-b.md). `Authorization` wird entfernt, Upstream-Cookies werden nicht gespeichert; App-Routen sind mit Registry und Autorisierung verbunden.

**Interne Registry-API (Entscheidung A):** [Vertrag, Aktivierung und Tests](docs/internal-registry.md). Portal bleibt alleinige Registry; ungecachte Service-Abfrage im Gateway. Proxyaktivierung erfolgt mit `GW_APP_UPSTREAM`; siehe Entscheidung B.

**Aktueller Migrationsstand:** siehe [Verhaltensabgleich und offene Freigaben](docs/migration-parity.md). OIDC-/Login- und Assertionbasis sind übernommen; App-Routen sind verdrahtet; Registry- und Upstream-Konfiguration sind für ihre Nutzung erforderlich.
Python/FastAPI-Dienst unabhängig vom bestehenden Portal. Keine Imports aus anderen
AWP-Repositories, keine Änderung ihrer Compose-Dateien oder der VM-Demo.
Der Adapter ist nicht Bestandteil dieser Stufe.

## Vorhandene Keycloak-Konfiguration verwenden

Es wird **keine zusätzliche Keycloak-Instanz und kein Demo-Realm** mehr angelegt.
Gefunden im bestehenden Portal:

| Quelle | Vorhandener Stand |
|---|---|
| `extras/compose/keycloak/hka-realm.json` | Realm `hka`, vertraulicher Client `portal`, Code Flow, verpflichtendes S256-PKCE, kein Password Grant |
| `dev/gateway.oidc.yml` | Lokaler Issuer `http://localhost:8180/realms/hka` |
| `dev/gateway.compose.yml` | Interne Discovery `http://keycloak:8080/realms/hka/.well-known/openid-configuration` |
| `extras/compose/keycloak/compose.yml` | Vorhandener Keycloak-Service, Port 8180, dynamischer Backchannel |
| `dev/keycloak/portal-client-secret` | Bestehende lokale Entwicklungs-Secretdatei; wird weder verändert noch in dieses Projekt kopiert |
| `dev/gateway.vm.yml` | Separater VM-Issuer unter HTTPS `/auth/realms/hka`; wird nicht verändert oder automatisch verwendet |

**Noch nicht vollständig geeignet:** Der exportierte Client erlaubt nur
`http://localhost:8000/oidc/callback` und den VM-Callback. Für den unabhängigen
Gateway auf 18080 fehlen im Export folgende freizugebende URLs:

* Redirect URI: `http://localhost:18080/oidc/callback`
* Post Logout Redirect URI: `http://localhost:18080/`

Ob ein Kollege diese URLs oder einen geeigneten separaten Client im laufenden
Realm bereits ergänzt hat, ist nicht verifiziert. Ein Realm-Export beweist nicht
seinen aktuellen Laufzeitstand. **Nicht erneut importieren und nicht zurücksetzen.**
Die zuständige Person muss einen geeigneten bestehenden Client samt Secret und
freigegebenen URLs bestätigen. Falls noch nicht vorhanden, muss sie die Freigabe
abstimmen; dieses Projekt ändert keine Clients automatisch. Ein eigener Client im
**bestehenden Realm** ist als spätere administrative Entscheidung möglich, wird
hier aber weder erfunden noch provisioniert.

## Lokal starten

Voraussetzungen: vorhandene laufende lokale Keycloak-Instanz, bestätigte
Client-Konfiguration, Python ≥ 3.13 (bevorzugt 3.14), uv, OpenSSL, Docker und Compose v2.

Vor dem Start folgende Werte setzen (die Beispiele sind Pfad-/Netzplatzhalter,
keine Zugangsdaten):

```sh
cd awp-hka-security-gateway
export GW_KEYCLOAK_NETWORK='<bestehendes Keycloak-Netz>'
export GW_OIDC_CLIENT_SECRET_FILE='/absoluter/externer/pfad/client-secret'
# Nur falls ein anderer, bereits eingerichteter Client bestätigt wurde:
# export GW_OIDC_CLIENT_ID='<bestaetigte-client-id>'
python3 tools/dev.py config
python3 tools/dev.py up
```

Den tatsächlichen Netzwerknamen lesend mit `docker network ls` / `docker inspect`
ermitteln. Aus den Compose-Projektnamen ergeben sich Kandidaten wie
`hka-portal_default` oder `hka-portal-keycloak_default`; **nicht ungeprüft übernehmen**.
Gateway wird deklarativ an dieses vorhandene externe Netz angeschlossen. Das
Netz wird weder erstellt noch entfernt; bestehende Container werden nicht verändert.
Das gemeinsame Entwicklungsnetz ist keine Produktionsisolation.

Client-Secret aus der autorisierten vorhandenen Konfiguration als Datei außerhalb
dieses Repositorys bereitstellen. Keine Secrets in `.env`, Befehlsargumenten oder
Commits speichern. Compose-Dateisecrets müssen für den Containerbenutzer lesbar
sein, beispielsweise Datei 0444 innerhalb eines privaten Hostverzeichnisses 0700.
Der Starthelfer verändert die bereitgestellte Secretdatei nicht und erzeugt kein
neues OIDC-Secret, keine Benutzer und keine Keycloak-Admin-Zugänge.

Er erzeugt ausschließlich den eigenen RSA-3072-Signaturschlüssel unter
`/tmp/hka-gateway-<uid>/` (privates Verzeichnis 0700; Schlüsseldatei 0444 für den
Container). Alternativer externer Ordner: `GW_LOCAL_DIR`. Vorhandene Schlüssel
werden nicht überschrieben. Ältere generierte Demo-Passwortdateien werden nicht
mehr benutzt; der Helfer löscht sie nicht automatisch.

* Gateway: **http://localhost:18080** – „Anmelden“ anklicken.
* IdP: vorhandenes **http://localhost:8180**, Realm **hka**.
* Benutzer: vorhandenes, freigegebenes Testkonto aus diesem Realm. Keine neuen
  Zugangsdaten werden angenommen oder ausgegeben.
* Eigener Redis-Service **gateway-redis**, ohne Hostport, getrennt vom Portal-Redis.
  Der eindeutige Name verhindert DNS-Verwechslungen im gemeinsamen Keycloak-Netz.

`/readyz` prüft Redis und Schlüssel, nicht den IdP. Bei fehlendem IdP ist Login
nicht möglich. Die funktionierende VM wird vom Starthelfer nicht angesprochen.

```sh
python3 tools/dev.py logs
python3 tools/dev.py down
```

Dies betrifft nur Gateway und seinen Redis; Keycloak ist kein Service dieses
Stacks. Die oben gesetzten Variablen auch für `down` beibehalten, da Compose sie
beim Einlesen benötigt. Ein Redis-Neustart verliert die lokalen Gateway-Sessions.

Gemeinsames Keycloak-SSO bedeutet: Ein IdP-Logout kann weitere Clients derselben
Browsersitzung abmelden. Tests deshalb in einem separaten privaten Browserfenster
oder mit dem isolierten Cookie-Jar des Smoke-Tests ausführen.

## Identitätsfluss und Grenzen

1. `/login` erzeugt State, Nonce, PKCE-Verifier und einen browsergebundenen
   Login-Cookie. Redis speichert die Transaktion mit TTL.
2. Keycloak führt Authorization Code Flow mit S256-PKCE aus. Kein Password Grant.
3. `/oidc/callback` konsumiert die Transaktion einmalig (`GETDEL`), prüft State,
   ID-Token-Signatur/Issuer/Audience/Ablauf/Nonce und rotiert eine bestehende Session.
   Danach erfolgt der geprüfte Rücksprung nach `next`, standardmäßig `/`; nicht mehr automatisch `/demo`.
4. Redis erhält `sub`, Name, die über `GW_ROLES_FILE`/`GW_GRANTS_FILE` gemappten Rollen, CSRF-Token und das ID-Token nur für
   den IdP-Logout. Access- und Refresh-Tokens werden nicht gespeichert.
5. `/me` verlangt eine Session. `/demo` erstellt nach Sessionprüfung ein RS256-JWT
   und übergibt es an einen kleinen **prozessinternen Mock-Empfänger**, der es
   ausschließlich mit öffentlichem Schlüssel prüft. Die Antwort zeigt Identität
   und Claim-Metadaten, **kein rohes Token, keine Session-ID, keine IdP-Tokens**.
6. `GET /logout` zeigt eine Bestätigung. `POST /logout` verlangt den CSRF-Token,
   lehnt fremde Origins ab, löscht Redis-Session und Cookie und startet nach
   Möglichkeit RP-Initiated Logout bei Keycloak. GET allein meldet nicht ab.

Eine ungültige/abgelaufene Sitzung ergibt **401**, nicht einen API-Loginredirect.
Redis-Fehler ergeben **503**, ohne Fallback auf Speicher oder anonyme Freigabe.
Die Sessionverwaltung entspricht jetzt dem Portal-Store: ein Redis-Hash mit
`created`/`last_seen`, ein Benutzerindex und ein Inaktivitäts-TTL. Aktivität
verlängert den Inaktivitäts-TTL höchstens einmal pro Touch-Intervall; die absolute
Laufzeit wird dadurch nicht verlängert. Es gibt weiterhin keinen Memory-Fallback.
Bekannte Nebenläufigkeitsrisiken des übernommenen Touch-Verfahrens sind unten
als noch nicht implementierte Verbesserungsmöglichkeiten dokumentiert.
Schon laufende Requests können durch Logout nicht rückwirkend gestoppt werden.
Ausgestellte JWTs sind ohne Onlineprüfung bis zum Ablauf gültig.

**Noch nicht integriert:** Portalweiterleitung, Adapter, Refresh-Verarbeitung,
Backchannel Logout, globale Benutzer-Sperren, Produktions-TLS,
Login-Rate-Limits und Origin-/Netzisolation beliebiger Micro-Apps. Es gibt keine
öffentliche Schnittstelle zum Signieren frei gewählter Claims/Audiences.
Der Testendpunkt ersetzt nur den ersten Portal-Identitätsfluss. Proxy und App-Zugriffsprüfung sind über die App-Routen verbunden; ohne erforderliche
Konfiguration verweigert der Gateway die Weiterleitung mit 503.

## Konfiguration

| Variable | Bedeutung / Standard |
|---|---|
| `GW_APP_UPSTREAM` | App-Container-URL-Schablone, z. B. `http://app-{slug}:8080`; ohne Wert keine Weiterleitung |
| `GW_PUBLIC_URL` | Öffentliche Gateway-Origin; für Produktion HTTPS |
| `GW_OIDC_ISSUER` | Exakter IdP-Issuer |
| `GW_OIDC_DISCOVERY_URL` | Optionaler interner Discovery-Zugang, Issuer bleibt öffentlich |
| `GW_OIDC_CLIENT_ID` | `portal`, aus vorhandener Konfiguration; bei bestätigtem anderem Client überschreiben |
| `GW_OIDC_CLIENT_SECRET_FILE` | Erforderliche Secretdatei |
| `GW_SIGNING_KEY_FILE` | Erforderlicher persistenter privater RSA-Schlüssel |
| `GW_REDIS_URL` | `redis://gateway-redis:6379/0` im Compose (Code-Standard: `redis://redis:6379/0`) |
| `GW_SESSION_SECONDS` | Absolute Sitzungsdauer, **300** (bestehender Name bleibt kompatibel) |
| `GW_SESSION_IDLE_SECONDS` | Inaktivitäts-TTL, **300** |
| `GW_SESSION_TOUCH_SECONDS` | Mindestabstand für Touch-Schreibvorgänge, **60**, kleiner als Idle-TTL |
| `GW_ASSERTION_SECONDS` | Assertiondauer, **60** |
| `GW_PORTAL_AUDIENCE` | Dedizierte Portal-Audience, `hka-portal-ui` |
| `GW_COOKIE_SECURE` | **true**; Compose setzt für HTTP-Loopback false |
| `GW_DEMO_ENABLED` | **false**; nur lokale Compose-Demo aktiviert `/demo` |

Produktions-Cookies heißen `__Host-hka_gateway_sid` / `__Host-hka_gateway_login`,
sind Secure, HttpOnly, SameSite=Lax, Path=/ und ohne Domain-Attribut.
Lokale HTTP-Cookies haben eigene Namen ohne `__Host-`. Unsichere öffentliche
HTTP-Origins werden abgelehnt. Signaturschlüssel werden niemals spontan erzeugt;
ohne lesbaren geeigneten Schlüssel startet der Dienst nicht.
Uvicorn-Accesslogs sind deaktiviert, damit Callback-Codes nicht im Querystring
erscheinen. Eigene Zugriffslogs enthalten nur Request-ID, Methode, Pfad und Status.

Fünf-Sekunden-Ablauftest statt fünf Minuten:

```sh
GW_SESSION_SECONDS=5 python3 tools/dev.py up
python3 tools/smoke.py --wait-expiry 6
```

Für eine externe TLS-Umgebung Compose nicht unverändert übernehmen: HTTPS-Origin,
IdP-Client, Secrets und Proxy-Vertrauen separat konfigurieren. Dieses Compose ist
ausschließlich an Loopback gebunden und keine VM-Deployment-Konfiguration.

## Assertionvertrag

`/.well-known/jwks.json` liefert die öffentlichen RSA-Schlüssel (aktuell sowie
optional nächster/vorheriger) mit `kid`, `use=sig`, `alg=RS256` und
`Cache-Control: public, max-age=300`. `kid` entspricht dem Portal-Fingerabdruck.
Issuer: `GW_ASSERTION_ISSUER`, sonst Gateway-Origin mit abschließendem `/`.

* Portal-UI: `aud=hka-portal-ui`, `token_use=portal-ui`; unverändert getrennt.
* Apps über `mint_app(session, app)`: ursprünglicher Portalvertrag mit
  `aud=[slug,"portal"]`, optional `"adapters"`, `azp=slug`, `scp=app.adapters`.
  Rollen werden mit `GW_ROLE_VOCABULARY` gefiltert. Kein neuer `token_use`-Claim.
* Gemeinsame Claims: `iss`, `sub`, `name`, `roles`, `iat`, `exp`, `jti`, `v:1`.
* Der Mock verlangt Portal-UI-Audience **und** Zweck und lehnt App-Assertions ab.
* Ohne konfigurierte Rollenquellen bleiben gemappte Rollen leer. Ohne
  Rollenvokabular enthält eine App-Assertion keine Rollen. Keine Rollen erfinden.

`portal` in App-Assertions ist die bestehende SDK-Navigations-Audience und darf
keine Freigabe für Portalverwaltung darstellen. Deren Integration bleibt offen.

## Python-Umgebung und Tests

Wie im Portal: uv verwaltet die lokale `.venv`, Laufzeitabhängigkeiten aus
`pyproject.toml` und die Testwerkzeuge aus der Gruppe `dev`. Mindestversion:
Python 3.13; `.python-version`, CI und Docker verwenden bevorzugt Python 3.14.
Docker und CI verwenden uv 0.11.0, entsprechend der uv-Version im Portal-Dockerfile.

```sh
make setup       # uv sync: Projekt und dev-Abhängigkeiten
make test        # uv run pytest -q tests, einschließlich HTTP-Integration
# Einzelner HTTP-Testlauf:
uv run pytest -q tests/test_app.py
```

Es werden keine Portal-Kit-, SDK-, Node.js- oder Adapter-Abhängigkeiten übernommen.
**Noch blockiert:** uv ist in der aktuellen Umgebung nicht verfügbar und kann
wegen fehlender Paketquellenerreichbarkeit nicht installiert werden. Eine eigene
`uv.lock` konnte deshalb noch nicht erzeugt werden. Sie wurde weder aus dem Portal
kopiert noch manuell zusammengesetzt. CI (`UV_LOCKED=1`) und Docker (`--frozen`)
setzen diese Datei voraus und sind bis zu ihrer Erstellung nicht vollständig nutzbar.

Sobald uv und Python 3.14 verfügbar sind, einmalig `uv lock` ausführen, die erzeugte
Gateway-Lockdatei versionieren und danach `make setup` / `make test` ausführen.
Laufzeitpakete werden künftig mit `uv add`, Testpakete mit `uv add --dev` gepflegt.
Die alte leere 3.12-venv ist nicht die neue Testumgebung; uv muss sie ersetzen.
Details: [Testumgebung und Ausführungsgrenzen](docs/test-environment.md).

Optionaler Docker-Testweg wie bisher:

```sh
python3 tools/dev.py test
```

Der Dockerbuild installiert aus `uv.lock`, im Testimage einschließlich `dev`,
im Laufzeitimage ohne Entwicklungsabhängigkeiten. Das Testimage läuft ohne Netz.
Die HTTP-Tests verwenden simulierten IdP und fakeredis; laufende Dienste sind
hierfür nicht erforderlich. Die Portalvergleiche benötigen zusätzlich das
benachbarte Portalrepository und werden im isolierten Testimage sonst übersprungen.

Echter Keycloak-Browserformular-Smoke-Test (Standardbibliothek; vorhandener IdP
und neuer Gateway müssen laufen; geeigneten Client vorher bestätigen):

```sh
export GW_TEST_USERNAME='<bestehendes freigegebenes Testkonto>'
export GW_TEST_PASSWORD_FILE='/absoluter/externer/pfad/testkonto-passwort'
python3 tools/smoke.py
```

Der Smoke-Test meldet sich mit dem bereitgestellten bestehenden Testkonto über das HTML-Formular
an, folgt dem echten OIDC-Callback, prüft den Demoempfänger und JWKS, meldet ab und
versucht das alte Session-Cookie erneut. Er benötigt keine Admin-API.

**Ausführungsstand in der Implementierungsumgebung:**

* Session-Store auf die Portalbasis umgestellt; aktuelle Kerntests prüfen
  Hash/TTL/Benutzerindex, Inaktivitätsablauf, Aktivitätsverlängerung mit absoluter
  Obergrenze, Touch-Drosselung, Session-/Indexlöschung, Einmaltransaktionen,
  Fehlerweitergabe und weiterhin Signierung/Zwecktrennung.
  Nach der Übernahme: **12 Kerntests erfolgreich** (Redis-Kommandotestdouble),
  zusätzlich **2 Keycloak-/Compose-Konfigurationstests erfolgreich**.
  Befehl: `PYTHONPATH=src python3 -m unittest discover -s tests -p test_core.py -v`.
* `python3 tools/dev.py config` erfolgreich (Compose-Schema/Interpolation).
* Nach Umstellung zwei zusätzliche Konfigurationstests erfolgreich:
  vorhandener Realm statt Import, genau Gateway/eigener Redis, externer IdP-Netzname
  und eindeutiger Redis-DNS-Name. Compose wurde dabei mit Testplatzhaltern validiert,
  keine echte IdP-Verbindung hergestellt.
* Ruff-Prüfung sowie Python-3.12-Syntaxprüfung bei der Erstimplementierung erfolgreich;
  damalige Demo-Realm-Datei als JSON validiert (inzwischen entfernt).
* Vollständige pytest-/HTTP-Tests vorbereitet, hier **nicht ausgeführt**: benötigte
  Pakete nicht installiert (`No module named pytest`); auch die Installation der
  Redis-Testabhängigkeiten war in dieser Umgebung nicht möglich.
* Echter Keycloak-, Redis- und Docker-Smoke-Test hier **nicht ausgeführt**:
  Zugriff auf Docker-Socket verweigert. Kein erfolgreicher Container-Build behauptet.

Redis-Ausfall wird im HTTP-Test durch einen werfenden Redis-Client geprüft; echte
Ausfallprobe nach lokalem Start: nur den `gateway-redis`-Service dieses Projekts stoppen,
mit vorhandener Browser-Session `/me` aufrufen (503), `/readyz` (503), `/healthz`
(200); danach den eigenen Redis-Service wieder starten. Dabei gehen Sessions
verloren. Dieser Test verändert keine Portal-/VM-Dienste.

## Wiederverwendung und spätere Portal-Integration

Siehe [Analyse und Herkunft](docs/analysis.md). Die vorhandenen Repositories bleiben
unverändert. Später benötigt das Portal einen verifizierten Request-UserContext
anstelle von `SessionDTO`/Rediszugriff. Nur öffentliche JWKS werden geladen;
OIDC-Secrets, IdP-Tokens und Signaturschlüssel bleiben im Gateway. Transport und
Headerfilter kommen in einer eigenen Integrationsstufe hinzu. Dabei fremde
`X-Portal-Assertion`/Gateway-Kontexte entfernen, Portalzweck strikt trennen,
Cookies nicht an Backends weiterleiten und keinen gemeinsamen Cookie-Jar verwenden.

## Redis-Übernahme und Datenformatwechsel

`src/gateway/redis_sessions.py` enthält die weitgehend übernommene Portalbasis
`RedisSessionStore` und `RedisLoginStore`. `sessions.py` enthält nur noch das
Sessionmodell und das Store-Protokoll, keine vereinfachte Store-Alternative und
keinen MemoryStore. Der Gateway nutzt die vorhandenen Methoden `create/get/delete/ping`
und `put/pop`; Rollen bleiben mangels RBAC-Integration leer.

Die Schlüssel entsprechen dem Portalmodell, mit eigenem Gateway-Präfix:

* `hka-gateway:v2:sess:<sid>`: Hash mit sub, name, roles, csrf, created, last_seen,
  optional id_token; EXPIRE für Inaktivität.
* `hka-gateway:v2:usr:<sha256(sub)>:sessions`: Set mit Session-IDs, TTL wie im Portal.
* `hka-gateway:v2:oidc:<lid>`: Einmaltransaktion mit TTL und GETDEL.

**Bestehende v1-Gateway-Sessions sind nicht kompatibel:** v1 enthielt JSON-Strings.
Der getrennte v2-Namespace vermeidet WRONGTYPE-Fehler; alte Cookies werden nicht
anerkannt, erneute Anmeldung erforderlich. Keine automatische Datenmigration,
kein Löschen alter Schlüssel; sie laufen durch ihre vorhandenen TTLs aus.
Portal-Schlüssel und Portal-Redis bleiben unverändert.

Das Sessionobjekt enthält zusätzlich `expires_at` für den bestehenden `/me`-Vertrag.
Es wird aus `created + absolute_seconds` berechnet, nicht zusätzlich gespeichert.
Die Redis-Basis prüft wie im Portal absolute Überschreitung beim Lesen (`>`).

**Identifiziert, hier ausdrücklich nicht implementiert:** atomarer Touch nur
bestehender Sessions (Race mit Logout/TTL), Begrenzung der physischen Redis-TTL auf
die verbleibende absolute Laufzeit, Bereinigung veralteter Benutzerindex-Einträge,
expliziter administrativer Benutzerwiderruf und Rollenaktualisierung. Der
Benutzerindex allein ist noch keine fertige Widerrufs-API. Diese Punkte sind
bewusst kein zusätzlicher Architektur-/Funktionsumfang dieser Übernahme.
