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
daher keine laufende Gateway-Identität. Lokal und auf der VM ist die Verwaltung
schreibend (`admin_write: true` in `dev/gateway.compose.yml` bzw. `gateway.vm.yml`).

### Abmelden

`POST /logout` beendet die Gateway-Session und leitet zum RP-initiated Logout von
Keycloak weiter (mit `id_token_hint`, ohne Rückfrage bei Keycloak).

- Portal-Kopf: Dialog, dann Formular mit dem CSRF-Wert der Session.
- Seitenrahmen der Apps (Portal-SDK ab 1.0.4-dev): Dialog, dann Formular **ohne**
  CSRF-Wert (Apps kennen ihn nicht). Das Gateway nimmt das nur an, wenn beide
  Browsersignale die eigene Herkunft belegen: `Origin` gleich `GW_PUBLIC_URL` und
  `Sec-Fetch-Site: same-origin`. Fehlt eines, leitet es auf `GET /logout` um.
- Fremde oder `null`-Origin sowie `same-site`/`cross-site`: 403; ein mitgeschickter
  falscher CSRF-Wert: 400. `GET /logout` zeigt weiterhin die Bestätigungsseite mit
  Formular (Fallback ohne JavaScript), ist aber nicht mehr nötig.

## Netz und Betrieb

Aufbau, Ports und Start stehen im [README](../README.md) (Abschnitte „Erster Start“
und „Aufbau“), die VM in [vm.md](vm.md). Kurz: Nur Gateway (18080) und Keycloak
(8180) haben Hostports, beide nur auf Loopback; auf der VM steht nginx mit HTTPS
davor. Interne Netze: `sessions` (Gateway–Redis), `identity` (Gateway–Keycloak),
`portal` (Gateway–Portal), `hka-portal-apps` (Gateway, Portal-Prober, Adapter und
die Apps). Apps erreichen weder Portal-Interna noch Redis oder Keycloak; das SDK
verlangt zusätzlich für jede App-Anfrage ein gültiges App-Token. Das Gateway sperrt
`/internal` und Unterpfade öffentlich (nginx zusätzlich, `nginx-portal.conf`).

Interne HTTP-Kommunikation setzt einen vertrauenswürdigen Docker-Host und geprüfte
Netzmitgliedschaft voraus. Service-Token authentifiziert den Aufrufer, JWT den
Benutzer. Es authentifiziert keine HTTP-Antwort kryptografisch: über Hostgrenzen
oder nicht vertrauenswürdige Netze ist serverauthentifiziertes TLS erforderlich.

**Browser-Isolation bleibt offen:** Portal und Apps liegen auf derselben Origin.
Das ist keine Sicherheitsgrenze gegenüber bösartigem App-JavaScript; insbesondere
können gleich-originige Apps Portal-Seiten/CSRF-Werte lesen. Daher nur mit
vertrauenswürdigen Apps verwenden. Eigene App-Origins sind vor dem Betrieb
unvertrauenswürdiger KI-Apps weiterhin erforderlich.

## Nachweise und Grenzen

- Gateway-Tests (`make test`): Entscheidungsvertrag, Header/Cookie-Filter,
  Fail-Closed, Session/OIDC/Logout, App-/Adapter-Assertions, Portal-Forwarding;
  Compose-Struktur per `docker compose config` (`test_registry_deployment.py`,
  `test_keycloak_reuse.py`) und der Vertrag mit dem Portal (`test_parity.py`:
  Gateway-Assertions gegen den echten Portal-Verifier, passende Konfigurationen).
- Portal-Tests: Assertionprüfung, keine eigenen Sessions, Rollen/Manifest,
  Admin-CSRF, App-Token nur für Navigation.
- `tests/test_gateway_flow.py` im Portal: Gateway, Portal und Test-App als ASGI-
  Anwendungen zusammen (braucht die Nachbar-Repos).
- Echter Durchlauf mit Keycloak, Redis und Browser: lokal nach `make server-up`,
  auf der VM nach [vm.md](vm.md).

## Häufige Fehler

| Meldung | Prüfen |
|---|---|
| Keycloak invalid redirect URI | Gateway-Callback `<GW_PUBLIC_URL>/oidc/callback` im Client `portal` freigegeben? |
| Keycloak invalid client | `oidc-client-secret` passt zum Client `portal` im Realm (lokal: `make server-init` übernimmt ihn). |
| Gateway 400 „OIDC metadata unavailable“ | Keycloak startet noch (lokal 20–40 s); sonst Netz `identity` und `GW_OIDC_DISCOVERY_URL`. |
| Portal 401 / Gateway 503 | Issuer inklusive abschließendem Slash, Audience, Uhrzeit, JWKS-Erreichbarkeit, gemeinsames Service-Token. Keine Token/Secrets in Logs posten. |
| App fehlt / 403 | Rolle der Person (Realm-Attribut → `roles.yml`), Manifest, Portalentscheidung. |
| POST 403 | Exakt die öffentliche Adresse verwenden (lokal `http://localhost:18080`); Origin-/CSRF-Prüfungen nicht abschalten. |
