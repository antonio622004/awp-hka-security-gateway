> **Historisch.** Zwischenstand der Migration (November 2026), nicht mehr gepflegt. Erwähnte Dateien wie
> `compose.yml` (Phase 1), `compose.portal.yml`, `compose.registry.yml`, `compose.vm.yml`, `deployment/` oder
> `tools/dev.py` gibt es nicht mehr. Aktuell: [README](../README.md), [Gateway–Portal](gateway-portal.md),
> [VM](vm.md).

**Fortschreibung Entscheidung B:** Proxykorrekturen und App-Routen sind implementiert; aktueller Stand in [proxy-decision-b.md](proxy-decision-b.md). Ältere offene Freigaben unten sind historische Zwischenstände.

**Fortschreibung Entscheidung A:** Die interne Registry-API ist implementiert; aktueller Vertrag und Aktivierungsgrenzen in [internal-registry.md](internal-registry.md). Die nachstehenden offenen Registry-Transportfragen beschreiben den vorherigen Stand. Entscheidung B bleibt offen.

# Verhaltensabgleich mit dem Portal – 2026-11-09

Das Portal, dessen Registry/UI/Navigation, Golden Masters, bestehende Compose-
Dateien und VM-Konfiguration wurden nicht geändert. Kein Dienst wurde neu verdrahtet.
Die vollständige Migration ist noch nicht abgeschlossen: notwendige Entscheidungen
wurden vor Implementierung der Dienstschnittstelle und vor Sicherheitskorrekturen
zur Rücksprache gestellt. Offene Antworten sind keine Freigabe.

## Herkunft und aktueller Stand

| Gateway-Datei | Portalquelle | Anpassung / Stand |
|---|---|---|
| `roles.py` | `auth/roles.py` | Unverändert übernommen: Claim-Zuordnung, Standardrollen, Grants. |
| `redirects.py` | `auth/redirects.py` | Unverändert übernommen: geprüftes relatives `next`, Login-URL. |
| `exceptions.py` | `service/exceptions.py` | Bestehende fachliche Exceptions übernommen. |
| `login_service.py` | `service/login_service.py` | Lokale Imports; Session-Modell statt UI-DTO; direkt `SessionStore.create/delete` statt Portal-SessionWriteService. Ablauf und Rücksprung entsprechen dem Portal. |
| `assertion_keys.py` | `auth/assertion_keys.py` | Lokaler Config-Import, Standardlogging; aktueller/nächster/vorheriger Schlüssel, Signieren und Prüfen aus dem Portal. Gateway bleibt ohne flüchtigen Laufzeit-Schlüsselfallback. |
| `assertion_service.py` | `service/assertion_service.py` | Lokale Imports, Standardlogging; nur benötigte App-Eigenschaften als Protocol statt UI-DTO. Originale App-Claims und Rollenfilter. |
| `assertions.py` | Bisheriger Gateway | Fassade nutzt übernommene Klassen; separater Portal-UI-Vertrag und Mock bleiben erhalten. |
| `app_service.py` | `service/app_service.py::find_authorized` | Nur Zugriffsalgorithmus übernommen; keine Menülogik und keine Registrykopie. Liefert Lesedeskriptor statt UI-DTO. Noch nicht an HTTP gebunden. |
| `proxy.py` | `web/proxy.py` | Mit lokalen Imports übernommen, bekannte Fehler dokumentiert, noch nicht instanziiert/geroutet. Sicherheitsänderungen stehen aus. |
| `config.py` | OIDC-/Assertion-/AppsConfig aus `core/config.py` | OIDC-Defaults jetzt RS256/ES256, 60 s Toleranz; Login-TTL 600 s; übrige bestehende Gateway-TTLs bleiben. |
| `app.py` | Portal-Login-/Logout-/JWKS-Router | LoginService eingebunden, Session-Cookie ohne Max-Age, Logoutstatus ohne Session/bei CSRF wie Portal, HTTPException-Header erhalten, Validierungsstatus 422, JWKS öffentlich cachebar. |

## Bewusst verbleibende Unterschiede

* Gateway-Session-Cookies und Redis-Namespace bleiben getrennt; bestehende
  Portal-/Gateway-Sessions werden nicht übernommen. Kein Memory-Fallback.
* Portal-UI-Assertions haben weiterhin eine dedizierte Audience und Tokenzweck.
  Sie werden nicht mit der alten SDK-Navigations-Audience `portal` vermischt.
* Gateway-Fehler bleiben Problem-JSON. Portal-HTML, Templates und Navigation
  werden nicht kopiert. `/me` und `/demo` liefern ohne Session weiterhin 401;
  der übernommene LoginRequiredError-Handler ermöglicht den Portal-Loginredirect
  für den späteren App-Router. Der Router ist noch nicht montiert.
* Bestehende zusätzliche Gateway-Prüfungen (TrustedHost, Logout-Origin,
  Cookie-/URL-Konfigurationsgrenzen, Mindestgröße des aktuellen RSA-Schlüssels)
  bleiben erhalten. Keine Sicherheitsprüfung wurde für bloße Gleichheit entfernt.
* Die globale Gateway-CSP bleibt vorerst unverändert. Sie ist für weitergeleitetes
  App-HTML ungeeignet; vor Aktivierung des Proxys muss ihr Geltungsbereich geklärt
  werden. Kein stilles Abschwächen einer Sicherheitsrichtlinie.
* Callback-Querystrings werden weiterhin nicht im Accesslog gespeichert.
* OIDC-Client behält seine vorherigen Gateway-Korrekturen (JSON-Fehlerbehandlung,
  expliziter Subject-Typ, Ressourcenfreigabe). Kein Token-Refresh hinzugefügt.

## Noch notwendige Entscheidungen / Integration

1. Registry bleibt im Portal. Der Zugriff auf dessen Snapshot (Slug, Rollen,
   Status und ggf. Upstream) braucht einen bestätigten Transportvertrag. Zur Wahl
   gestellt: nur injizierbare lesende Testgrenze, gemeinsame schreibgeschützte
   Manifeste oder separat zu vereinbarende interne Portal-API. Nichts davon ist
   als reale Anbindung implementiert. Die übernommene Geschäftslogik nutzt intern
   weiterhin die bestehende `snapshot().get(slug)`-Abhängigkeit.
2. Für App-Routen fehlen genau deshalb Providerbindung, Proxyaktivierung und
   Registrierung von `/apps/{slug}` bzw. `/apps/{slug}/{path}`. Kein Fallback auf
   aus Browserdaten abgeleitete Upstreams und keine Zulassung ohne Policy.
3. Sicherheitsfreigabe vor Proxyaktivierung: HTTPX-Cookie-Jar deaktivieren und
   `Authorization` entfernen? Beide Änderungen wurden ausdrücklich angefragt,
   aber ohne Antwort noch nicht vorgenommen. Der kopierte Proxy ist nicht aktiv.
4. Weitere geerbte Proxygrenzen: `Location` nutzt einfachen Präfixvergleich;
   durch `Connection` benannte weitere Hop-by-hop-Header werden nicht vollständig
   behandelt; Origin-Fallback vergleicht nur netloc; Uploads werden gepuffert;
   keine WebSockets. Keine stillen Korrekturen oder neuen Protokollfeatures.
5. Gemeinsame Browser-Origin, Docker-Netzisolation und Touch/Logout-Race bleiben
   bekannte Risiken der bestehenden Plattform. Keine Architekturänderung hier.
6. Portalweiterleitung, öffentlicher JWKS-Verifikationsvertrag im Portal und
   SDK-Navigation benötigen weitere Integration. Die neuen Schlüsseldateien und
   IdP-Tokens bleiben ausschließlich beim Gateway. Kein Portalzugriff auf Secrets.

## Konfiguration ohne erfundene Rollenwerte

Zusätzlich zum bisherigen Gateway sind über `Settings.from_env()` möglich:

| Variable | Bedeutung |
|---|---|
| `GW_ROLES_FILE` | Bestehende Rollenmapping-YAML; fehlt sie, bleibt Mapping leer. |
| `GW_GRANTS_FILE` | Optionale bestehende Subject-Grants. |
| `GW_ROLE_VOCABULARY` | Kommagetrenntes bestehendes Rollenvokabular für App-Assertions; leer bedeutet keine App-Rollen. |
| `GW_ASSERTION_ISSUER` | Exakter bisheriger Assertion-Issuer; ohne Wert weiterhin öffentliche Gateway-Origin plus `/`. |
| `GW_SIGNING_KEY_NEXT_FILE`, `GW_SIGNING_KEY_PREVIOUS_FILE` | Optionale bestehende Rotationsschlüssel, nur öffentliche Teile erscheinen im JWKS. |
| `GW_LOGIN_SECONDS` | Login-Transaktions-TTL, jetzt Portalstandard 600. |
| `GW_OIDC_ID_TOKEN_ALGS` | Kommagetrennt, Portalstandard `RS256,ES256`. |
| `GW_OIDC_CLOCK_LEEWAY_SECONDS` | Portalstandard 60. |

Die unveränderte Compose-Datei reicht diese zusätzlichen Variablen/Dateien noch
nicht durch. Für unabhängige Python-Tests können Settings direkt injiziert werden.
Keine Mappingdatei, kein Secret und keine Registry wurde automatisch eingebunden.

## Tests und Grenzen des Nachweises

Erfolgreich ausgeführt:

* 12 bestehende Kerntests mit Redis-Kommandotestdouble.
* 6 neue Vergleichstests in `tests/test_parity.py`: Rücksprungfilter,
  Rollenmapping, Login-Orchestrierung inkl. Rotation/Replay, App-Claims/JWKS mit
  drei Schlüsseln, Autorisierungsreihenfolge und OIDC-Standardparameter.
* 2 bestehende Keycloak-/Compose-Konfigurationstests ohne laufende Dienste.

Die Vergleichstests führen die Originalfunktionen/-klassen aus den benachbarten
Portalquelldateien mit isolierten Importabhängigkeiten aus. Sie ersetzen weder
vollständige Portaltests noch HTTP-/Netzwerk-/Deploymenttests. Ohne benachbartes
Portalrepository werden diese Vergleiche übersprungen (auch im isolierten
Gateway-Testimage ohne Portalquellen).

Zusätzliche HTTP-Regressionstests wurden in `tests/test_app.py` ergänzt:
Rollen im Callback, sicheres `next`, Cookie-Persistenz, JWKS-Caching, Logoutstatus
und `Allow` bei 405. Vorhandener Test erwartet jetzt CSRF-Status 400 wie Portal.
Smoke-Helfer ruft `/demo` explizit ab, statt den alten Callback auf `/demo` anzunehmen.

Nicht erfolgreich ausführbar: vollständiges pytest (Modul fehlt); Paketbezug aus
der Umgebung fehlgeschlagen. Keine Aussage über erfolgreichen echten Login,
Containerbuild, SDK-Gesamtfluss oder aktives Proxying. Der vorhandene Docker-Testhelfer
wurde versucht und scheiterte am verweigerten Zugriff auf `/var/run/docker.sock`. Offene Proxytests folgen
erst mit bestätigter Sicherheitsbehandlung und Provider-/Routingintegration.

Aus dem Gatewayverzeichnis:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p test_core.py -v
PYTHONPATH=src python3 -m unittest discover -s tests -p test_parity.py -v
PYTHONPATH=src python3 -m unittest discover -s tests -p test_keycloak_reuse.py -v
python3 -m pytest -q
```
