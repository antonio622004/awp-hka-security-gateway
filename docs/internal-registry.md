# Interne Registry-API – Entscheidung A

> **Historisch.** Zwischenstand der Migration (November 2026), nicht mehr gepflegt. Erwähnte Dateien wie
> `compose.yml` (Phase 1), `compose.portal.yml`, `compose.registry.yml`, `compose.vm.yml`, `deployment/` oder
> `tools/dev.py` gibt es nicht mehr. Aktuell: [README](../README.md), [Gateway–Portal](gateway-portal.md),
> [VM](vm.md).

## Vertrag und Umsetzung

`GET /internal/apps/{slug}/access` im Portal liest direkt
`portal.registry.snapshot().get(slug)`. Antwort:

```json
{"slug":"noten","roles":["student"],"status":"healthy","adapters":["noten:read"]}
```

Unbekannte App: 404 mit `{"detail":"App not found"}`. Bekannte Zustände werden
unverändert geliefert; erst der Gateway entscheidet über deren Zugänglichkeit.
Alle Antworten sind `no-store`. Kein Benutzerlogin, keine zweite Registry und
keine neuen Adapterfunktionen. Das bisherige Registrieren, Nachladen und Probing
im Portal bleibt unverändert.

Der Gateway nutzt `RegistryClient` als lesenden Adapter für den bestehenden
`AppService`: jeder Aufruf von `find_authorized()` liest die App erneut per HTTP.
`snapshot()` am Client ist nur ein Kompatibilitätsadapter, kein lokaler Snapshot
und kein Cache. Die vorhandene Reihenfolge 404 → Anmeldung → Rolle → Status
bleibt erhalten. `mint_app()` nutzt weiterhin Slug und Adapter-Scopes aus dem
Deskriptor, einschließlich `scp`, `azp` und der bisherigen Audience-Liste.

Der Client prüft Antwortfelder, Slug, Rollen, Status, Adapter-Scopes, Content-Type
und Größe (max. 64 KiB). Timeout (2 s), ungültige Daten, Redirects, 401/403 oder
andere Fehler werden zu `RegistryUnavailableError`; der Gateway antwortet 503.
Es gibt keinen Rückgriff auf alte Daten. Nur die definierte 404-Antwort bedeutet
unbekannte App; eine fehlende API/HTML-404 gilt als Fehler. Browser-Credentials
werden nicht für den Serviceaufruf verwendet; Redirects und Umgebungs-Proxys sind aus.

## Zugriffsschutz und Aktivierung

* Separates zufälliges Service-Token: mindestens 32 Zufallsbytes, beispielsweise
  `secrets.token_urlsafe(32)` (43 base64url-Zeichen). Kein OIDC-Token oder JWT-Key.
* Token nur als externe Datei an genau Portal und Gateway mounten. Nicht in Git,
  Composewerten, URL oder Logs speichern. Portal vergleicht zeitkonstant und
  akzeptiert weder Session-Cookie noch Browser-Assertion als Serviceanmeldung.
* Portal ohne `PORTAL_REGISTRY_SERVICE_TOKEN_FILE`: API nicht registriert.
  Konfigurierte fehlende/ungeeignete Datei: Start schlägt fehl. Token wird beim
  Start gelesen; Rotation erfordert das koordinierte Neustarten beider Dienste.
* Öffentliche NGINX-Konfiguration sperrt `/internal` und `/internal/…` mit 404.
  **Diese Sperre zuerst installieren/prüfen, erst danach die API aktivieren.**
  Keine weiteren öffentlichen Reverse-Proxys auf die interne API erlauben.
* Beide Portal-/Gateway-Hostports bleiben an Loopback gebunden. Ein eigenes
  Docker-Netz nur für Portal/Gateway ist nötig. Tokenbesitz ist keine
  kryptografische Prozessidentität; andere Dienste erhalten weder Netz noch Secret.
  Hostadministratoren bleiben vertrauenswürdig. Außerhalb eines vertrauenswürdigen
  internen Netzes ist zusätzlich TLS erforderlich.

Vorbereitet, nicht gestartet oder auf der VM ausgerollt:

| Datei | Wirkung |
|---|---|
| Portal `extras/compose/vm/compose.registry.yml` | Opt-in für Secret und Netz; Alias `portal-registry`, bestehendes Portaldefaultnetz bleibt. |
| Gateway `compose.registry.yml` | Opt-in für Service-Client, dasselbe Secret und Netz; bestehende Netze bleiben. |
| Portal `extras/compose/vm/nginx-portal.conf` | Öffentliche Sperre, muss vom Betreiber tatsächlich installiert werden. |

Betreiber setzt auf beiden Seiten `HKA_REGISTRY_NETWORK` und
`HKA_REGISTRY_SERVICE_TOKEN_FILE` (absoluter externer Pfad). Das externe Netz muss
vorher ausdrücklich als intern angelegt und auf Mitglieder geprüft werden:

```sh
docker network create --internal "$HKA_REGISTRY_NETWORK"
```

Die Secretdatei muss für die jeweiligen Containerbenutzer lesbar sein. Bei
Compose-Dateimounts nicht auf `uid`/`mode`-Umschreibung vertrauen: beispielsweise
Datei 0444 innerhalb eines ausschließlich vom Betreiber zugänglichen externen
0700-Verzeichnisses. Nur die einzelne Datei an die beiden Dienste mounten.

Compose jeweils mit Basisdatei und Ergänzung verwenden:

```sh
# Im Portalrepository:
docker compose -f extras/compose/vm/compose.yml -f extras/compose/vm/compose.registry.yml config --quiet
# Im Gatewayrepository:
docker compose -f compose.yml -f compose.registry.yml config --quiet
```

Ohne Ergänzung verhalten sich die vorhandenen Stacks unverändert. Für Nutzung
muss das Portalimage mit dem neuen Code neu gebaut werden. Kein laufender Stack
wurde geändert; die öffentliche Unerreichbarkeit ist vor Deployment extern zu
prüfen. Composevalidierung beweist keine Netz- oder NGINX-Laufzeitkonfiguration.

Ohne Compose lauten die Variablen:
`PORTAL_REGISTRY_SERVICE_TOKEN_FILE` beim Portal;
`GW_REGISTRY_URL` und `GW_REGISTRY_SERVICE_TOKEN_FILE` beim Gateway.
Gateway-URL und Secretdatei müssen gemeinsam konfiguriert sein.

## Fortschreibung Entscheidung B

Die freigegebenen Proxykorrekturen und die App-Routen sind inzwischen verbunden.
`GW_APP_UPSTREAM` aktiviert den Proxy; die bestehende Rollen-/Assertionlogik nutzt
die hier beschriebene ungecachte API. Details und Nachweisgrenzen:
[proxy-decision-b.md](proxy-decision-b.md). Das Portal wurde für B nicht verändert.

## Tests

* Gateway: HTTPX-MockTransport prüft Serviceauthentifizierung, ungecachte Änderungen,
  unbekannte Apps, Status-/JSON-/Schemafehler, Redirects, Timeout, fehlende API,
  keine alten Daten bei Ausfall sowie Rollenprüfung und den bisherigen JWT-Vertrag.
* Portal: HTTP-Tests für optionale Aktivierung, Service-Token, doppelte Header,
  unveränderten Snapshotvertrag, Änderungen, fehlende Apps und ungeeignete Secrets.
* Gateway-HTTP-Test: Testempfänger prüft Registry → Sessionrollen → Autorisierung →
  Assertion sowie 403/404/503 und keine Signierung bei verweigertem Zugriff.
* Deploymenttests validieren beide Composekombinationen ohne Dienste zu starten
  und prüfen die öffentliche NGINX-Sperre als Konfigurationstext.

Die ausführbaren Unit-/Vergleichs-/HTTPX-/Composeprüfungen wurden durchgeführt.
Die vollständigen Portal-/Gateway-HTTP-Tests konnten in dieser Umgebung nicht
laufen (fehlende bzw. inkompatible Abhängigkeiten). HTTPX 0.28.1 wurde lesend aus
der vorhandenen Golden-Master-Umgebung geladen; keine Pakete oder Golden Masters
wurden geändert. Kein echter Netzwerk-, VM- oder Dockerlaufzeitnachweis.
