# HKA Security-Gateway

Einziger Eingang zum HKA-Portal: Anmeldung bei Keycloak (OIDC mit PKCE), Sessions in Redis, frische signierte
Assertions für das Portal und die Apps, Weiterleitung zu Portal (`/`) und Apps (`/apps/<slug>/`).
Das Portal und die Apps haben keine eigene Anmeldung; sie prüfen nur die Assertion des Gateways.

Dieses Repo enthält außerdem die Compose-Bausteine für den Gesamtstart: `gateway/`, `redis/`, `keycloak/`,
`server/` (lokal) und `vm/` (Test-VM). Portal-Backend und bwSync-Adapter kommen per `include` aus ihren Repos.

## Erster Start

Voraussetzungen: Linux, WSL2 oder DevContainer; Docker mit Compose v2; [uv](https://docs.astral.sh/uv/); git.

1. Die Repos **nebeneinander** in einen Ordner klonen (die Compose-Dateien verweisen mit `../` aufeinander):

   ```text
   awp/
   ├── awp-hka-security-gateway/   dieses Repo (Gateway, Redis, Keycloak, server/, vm/)
   ├── awp-hka-intranet-portal/    Portal-Backend und Portal-SDK
   ├── awp-hka-adapter/            bwSync-Adapter
   └── app-syncshare-test/         eine App (oder eine eigene aus dem Golden Master)
   ```

2. Einmalig vorbereiten (überschreibt nichts, gibt keine Secrets aus):

   ```sh
   cd awp-hka-security-gateway
   make server-init
   ```

   Legt Secrets in `server/.secrets/` an (Signierschlüssel, Registry-Token, Adapter-Schlüssel, Client-Secret
   aus dem Realm), schreibt `server/.env` aus `server/.env.example` und die Datenordner des Portals
   (`awp-hka-intranet-portal/.local/portal/`). Den Adapter-Schlüssel nie neu erzeugen, wenn schon
   bwSync-Zugänge gespeichert sind.

3. Stack bauen und starten:

   ```sh
   make server-up      # docker compose -f server/compose.yml up -d --build
   ```

   Keycloak braucht beim ersten Start 20–40 Sekunden. Dann **http://localhost:18080** öffnen und mit einer
   Testperson aus `keycloak/hka-realm.json` anmelden (nur lokal; Studierende z. B. `alexandru`, `antonio`,
   Verwaltung `admin`). Keycloak-Konsole: http://localhost:8180 (Benutzer `admin`, Passwort in `server/.env`).

4. Eine App in das Netz `hka-portal-apps` bringen und im Portal registrieren:

   ```sh
   cd ../app-syncshare-test
   make deploy-local   # baut das Image, startet app-syncshare-test, registriert das Manifest
   ```

   Danach steht die App nach einigen Sekunden im Menü: http://localhost:18080/apps/syncshare-test/

5. Optional bwSync: eigenen bwSync&Share-Zugang (Anmeldename und App-Passwort) für die eigene Person hinterlegen:

   ```sh
   docker compose -f server/compose.yml exec adapter python -m app.manage_credentials
   ```

Anhalten: `make server-down` (Volumes und Secrets bleiben). Nach Änderungen in einem der Repos wieder
`make server-up` (baut neu).

## Aufbau

```text
Browser ──► :18080 gateway ──┬─ sessions ──► gateway-redis
   │                         ├─ identity ──► keycloak
   │                         ├─ portal ────► backend (Portal)
   │                         └─ hka-portal-apps ─► app-<slug> ──► adapter ──► bwSync&Share (Internet)
   └──► :8180 keycloak (Anmeldeseite)                ▲ Prober des Portals
```

| Dienst | Herkunft | Aufgabe | Netze | Hostport |
|---|---|---|---|---|
| `gateway` | `gateway/compose.yml` | Anmeldung, Sessions, Assertions, Weiterleitung | default, sessions, identity, portal, hka-portal-apps | `127.0.0.1:18080` |
| `gateway-redis` | `redis/compose.yml` | Sessions (ohne Persistenz) | sessions | – |
| `keycloak` | `keycloak/compose.yml` | IdP, Realm `hka`, Login-Theme | identity, keycloak-port | `127.0.0.1:8180` |
| `backend` | Portal `extras/compose/backend/compose.yml` | Portal: Menü, Registry, Status, Verwaltung | portal, hka-portal-apps | – |
| `adapter` | Adapter `compose.yml` | bwSync&Share per WebDAV | hka-portal-apps, bwsync-egress | – |
| `app-<slug>` | `make deploy-local` der App | die Apps | hka-portal-apps | – |

| Netz | Intern | Wer |
|---|---|---|
| `sessions` | ja | Gateway, Redis |
| `identity` | ja | Gateway, Keycloak |
| `portal` | ja | Gateway, Portal |
| `hka-portal-apps` (fester Name) | ja | Gateway, Portal (Prober), Adapter, Apps |
| `bwsync-egress` | nein | nur Adapter (HTTPS zu bwSync) |
| `default`, `keycloak-port` | nein | nur für die Hostports (an internen Netzen veröffentlicht Docker keine Ports) |

Hostports nur auf Loopback; auf der VM steht nginx mit HTTPS davor (`/` → 18080, `/auth/` → 8180), siehe
[docs/vm.md](docs/vm.md). Persistent: Volume `hka-adapter-data` (verschlüsselte bwSync-Zugänge) und die
Portal-Ordner `manifests`, `status`, `registry`. Secrets sind Dateien außerhalb von Git (`server/.secrets/`,
auf der VM `/srv/portal/gateway/secrets/`).

Werte, die sich zwischen lokal und VM unterscheiden, stehen in `server/.env` bzw. `vm/.env`; alles andere
hat lokale Standardwerte in den Compose-Dateien. Compose liest die `.env` im Ordner der Datei, die man mit
`-f` angibt, für alle eingebundenen Dateien.

## Make-Ziele

| Ziel | Was passiert |
|---|---|
| `make setup` / `make test` | Python-Umgebung (uv) / Tests |
| `make server-init` | lokale Secrets, `server/.env`, Portal-Ordner (einmalig, überschreibt nichts) |
| `make server-up` / `make server-down` | lokalen Stack bauen und starten / anhalten |
| `make vm-images` | Images mit VM-Werten bauen und als ein `tar.gz` speichern (siehe [docs/vm.md](docs/vm.md)) |
| `make vm-check` | `vm/compose.yml` mit `vm/.env.example` prüfen (`docker compose config`) |
| `make keycloak-theme-update THEME_DIST=…` | Kit-Kopie für das Keycloak-Login-Theme aus dem Portal übernehmen |

## Identitätsfluss

1. `/login` erzeugt State, Nonce, PKCE-Verifier und einen browsergebundenen Login-Cookie; Redis speichert die
   Transaktion mit TTL. Anonyme Aufrufe von `/` und `/apps/…` starten die Anmeldung selbst.
2. Keycloak führt den Authorization Code Flow mit S256-PKCE aus. Kein Password Grant.
3. `/oidc/callback` konsumiert die Transaktion einmalig (`GETDEL`), prüft State, ID-Token-Signatur, Issuer,
   Audience, Ablauf und Nonce, rotiert eine bestehende Session und springt geprüft nach `next` zurück.
4. Redis erhält `sub`, Name, die über `GW_ROLES_FILE` gemappten Rollen, CSRF-Token und das ID-Token nur für
   den IdP-Logout. Access- und Refresh-Tokens werden nicht gespeichert.
5. Jede Anfrage an Portal oder App bekommt eine frische Assertion (60 s), nie aus einem Cache.
6. Abmelden: `POST /logout` löscht Session und Cookie und leitet zum Logout bei Keycloak weiter. Portal und
   Seitenrahmen der Apps schicken es direkt aus einem Dialog; Schutz über CSRF-Wert bzw. Origin und
   `Sec-Fetch-Site` (Details: [docs/gateway-portal.md](docs/gateway-portal.md#abmelden)).
   `GET /logout` zeigt als Fallback eine Bestätigungsseite.

Ungültige oder abgelaufene Sitzung: **401** bzw. neue Anmeldung; Redis-Fehler: **503**, ohne Fallback.
Ausgestellte Assertions sind bis zu ihrem Ablauf gültig. Noch nicht umgesetzt: Refresh, Backchannel Logout,
globale Sperren, Login-Rate-Limits und getrennte Origins für Apps (siehe Browser-Isolation in
[docs/gateway-portal.md](docs/gateway-portal.md#netz-und-betrieb)).

## Konfiguration

Standardwerte aus `gateway/compose.yml` (lokal); die VM überschreibt sie in `vm/.env`.

| Variable | Bedeutung | Standard |
|---|---|---|
| `GW_PUBLIC_URL` | öffentliche Origin (VM: HTTPS) | `http://localhost:18080` |
| `GW_ASSERTION_ISSUER` | `iss` der Assertions | `GW_PUBLIC_URL` + `/` |
| `GW_COOKIE_SECURE` | Secure-Cookies (VM: `true`) | `false` |
| `GW_OIDC_ISSUER` | Issuer, wie der Browser Keycloak sieht | `http://localhost:8180/realms/hka` |
| `GW_OIDC_DISCOVERY_URL` | Discovery intern | `http://keycloak:8080/realms/hka/.well-known/…` |
| `GW_OIDC_CLIENT_ID` | Client im Realm | `portal` |
| `GW_SESSION_SECONDS` / `GW_SESSION_IDLE_SECONDS` | höchstens / Leerlauf | 8 h / 30 min |
| `GW_ASSERTION_SECONDS` | Laufzeit einer Assertion | 60 s |
| `GW_DEMO_ENABLED` | Testendpunkt `/demo` | `false` |
| `GW_ROLES_FILE`, `GW_ROLE_VOCABULARY` | Zuordnung IdP-Claims → Rollen (`roles.yml` aus dem Portal), erlaubte Rollen | fest |
| `GW_PORTAL_UPSTREAM`, `GW_REGISTRY_URL`, `GW_APP_UPSTREAM` | Portal und Apps intern | `http://backend:8000`, `http://app-{slug}:8080` |
| `*_SOURCE` in `.env` | Pfade der Secret-Dateien und von `roles.yml` auf dem Host | – |

Produktions-Cookies heißen `__Host-hka_gateway_sid` / `__Host-hka_gateway_login` / `__Host-hka_gateway_lang`
(Secure, HttpOnly, SameSite=Lax, Path=/). Signierschlüssel werden nie spontan erzeugt; ohne lesbaren Schlüssel startet der
Dienst nicht. Zugriffslogs enthalten nur Request-ID, Methode, Pfad und Status.

## Sprache (Deutsch und Englisch, HKA-101)

Das Gateway entfernt Cookies auf dem Weg zu Portal und Apps. Darum speichert es die Sprachwahl selbst:

- `GET /sprache/<de|en>?next=<Pfad>` setzt das Cookie `hka_gateway_lang` (ein Jahr) und leitet mit 303 zum Pfad zurück
  (`redirects.sanitize_return`: nur Pfade auf diesem Server, sonst `/`). Ein anderer Code ergibt 404. Der Umschalter im Portal
  ruft diese Adresse (Portal-Konfiguration `language_switch: true`).
- Die Sprache einer Anfrage ist das Cookie, sonst die erste unterstützte Sprache aus `Accept-Language` (`en-GB` zählt als `en`),
  sonst Deutsch (`language.pick_language`).
- Portal und Apps bekommen sie als `Accept-Language: de` oder `en`; die mitgeschickte Kopfzeile wird ersetzt. Das SDK der Apps
  und das Portal lesen nur diese Kopfzeile. Das Menü des SDK (`GET /nav` mit Bearer-Token) bleibt unverändert, das SDK schickt die
  Sprache selbst mit.
- Beim Login schickt das Gateway `ui_locales=<de|en>` an Keycloak. Realm (`supportedLocales`) und Theme `hka`
  (`locales=de,en`, `messages_en.properties`) haben beide Sprachen.
- Die Bestätigungsseite von `GET /logout` gibt es in beiden Sprachen.

## Assertionvertrag

`/.well-known/jwks.json` liefert die öffentlichen RSA-Schlüssel (aktuell sowie optional nächster/vorheriger)
mit `kid`, `use=sig`, `alg=RS256` und `Cache-Control: public, max-age=300`.

* Portal-UI: `aud=hka-portal-ui`, `token_use=portal-ui`, dazu `csrf` der Session.
* Apps: `aud=[slug, "portal"]`, bei Adapterrechten zusätzlich `"adapters"`, `azp=slug`, `scp` aus dem Manifest
  (vom Portal entschieden). Rollen gefiltert mit `GW_ROLE_VOCABULARY`. `portal` erlaubt nur die SDK-Navigation.
* Gemeinsam: `iss`, `sub`, `name`, `roles`, `iat`, `exp`, `jti`, `v: 1`.

Den Vertrag mit dem Portal (Entscheidungs-API, CSRF, Abmelden, Netze) beschreibt
[docs/gateway-portal.md](docs/gateway-portal.md).

## Sessions in Redis

* `hka-gateway:v2:sess:<sid>`: Hash mit sub, name, roles, csrf, created, last_seen, optional id_token; EXPIRE
  für Inaktivität. Aktivität verlängert höchstens einmal pro `GW_SESSION_TOUCH_SECONDS`, nie über die
  absolute Laufzeit hinaus.
* `hka-gateway:v2:usr:<sha256(sub)>:sessions`: Set mit Session-IDs.
* `hka-gateway:v2:oidc:<lid>`: Einmaltransaktion der Anmeldung (GETDEL).

Redis läuft ohne Persistenz: Nach einem Neustart müssen sich alle neu anmelden. Bekannt und nicht umgesetzt:
atomarer Touch nur bestehender Sessions, Begrenzung der Redis-TTL auf die Restlaufzeit, Bereinigung des
Benutzerindex, administrativer Widerruf.

## Tests

```sh
make setup
make test
```

Die Tests prüfen auch die Compose-Struktur mit `docker compose config` (ohne Dienste zu starten) und den
Vertrag mit dem Portal; dafür müssen Docker und die Nachbar-Repos vorhanden sein, sonst werden diese Tests
übersprungen. `tools/smoke.py` ist ein Browser-Formular-Test gegen ein laufendes Gateway mit
`GW_DEMO_ENABLED=true` (`GW_TEST_USERNAME`, `GW_TEST_PASSWORD_FILE`).

## Weitere Dokumente

* [docs/gateway-portal.md](docs/gateway-portal.md): Vertrag Gateway ↔ Portal, CSRF, Abmelden, Netze, häufige Fehler
* [docs/vm.md](docs/vm.md): Test-VM Schritt für Schritt
* Historisch (Migration November 2026): [analysis.md](docs/analysis.md), [migration-parity.md](docs/migration-parity.md),
  [internal-registry.md](docs/internal-registry.md), [proxy-decision-b.md](docs/proxy-decision-b.md)
