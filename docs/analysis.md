> **Historisch.** Zwischenstand der Migration (November 2026), nicht mehr gepflegt. Erwähnte Dateien wie
> `compose.yml` (Phase 1), `compose.portal.yml`, `compose.registry.yml`, `compose.vm.yml`, `deployment/` oder
> `tools/dev.py` gibt es nicht mehr. Aktuell: [README](../README.md), [Gateway–Portal](gateway-portal.md),
> [VM](vm.md).

**Fortschreibung:** Aktueller Stand und noch offene Freigaben in [migration-parity.md](migration-parity.md). Die folgende Phase-1-Analyse ist die historische Ausgangsbasis.

# Analyse, Wiederverwendung und Abgrenzung

Untersuchter Portalstand: `b7823bb` (05.11.2026).
Alle bisherigen Repositories und die VM-Konfiguration bleiben unverändert.

| Vorhandene Komponente | Ergebnis / Verwendung im neuen Dienst |
|---|---|
| `extras/compose/keycloak/{compose.yml,Dockerfile,hka-realm.json}` | Keycloak 26.4, Realm, Benutzer und OIDC-Client vorhanden. Bestehender Stack an 8180 verwendet bekannte Testsecrets und ist mit Portal-Theme gekoppelt. Wird nun wiederverwendet: Realm hka, Issuer an 8180 und bestehender Client (sofern Gateway-Callback freigegeben). Kein eigener Keycloak-Service/Realm; keine Realmimporte. Fehlende Freigaben siehe README. |
| `dev/gateway.oidc.yml`, `gateway.compose.yml`, `gateway.vm.yml` | Öffentlicher Issuer und interner Discovery-Zugang bereits getrennt. Dieses Modell übernommen; eigene Gateway-Origin/Redirect-URI, bestehender bestätigter Client. Callback-Freigabe für 18080 im vorhandenen Export noch nicht enthalten. |
| `auth/oidc.py` | Als eigenständige Kopie nach `gateway/oidc.py` extrahiert, Importpfad angepasst. Code Flow, PKCE, Discovery, JWKS, Nonce-/Claim-Prüfung und IdP-Logout wiederverwendet; JSON-Fehler vereinheitlicht, Subject-Typ geprüft, Client-Cleanup ergänzt. |
| `service/login_service.py`, `router/oidc_router.py` | State/Nonce/Browserbindung, einmaliges Redis-GETDEL und Sessionrotation übernommen, ohne PortalContext/Registry/Views/RoleMapper. |
| `auth/redis_sessions.py` | RedisSessionStore und RedisLoginStore jetzt weitgehend vollständig übernommen: Hashes, Benutzerindex, Idle-TTL, absolute Laufzeit, Touch-Drosselung, Löschen und GETDEL. Eigener v2-Namespace, injizierbare Uhr und expires_at-Metadatum; keine Memory-Alternative und keine neue Benutzersperr-/RBAC-Funktion. |
| `auth/assertion_keys.py` | RFC-7638-kid, RSA-JWK und PyJWT-RS256-Verfahren übernommen. Nur persistenter Schlüssel; keine Dev-Schlüsselerzeugung beim Serverstart. |
| `service/assertion_service.py` | Gemeinsame Claims beibehalten. Portal erhält eigene Audience und expliziten Zweck; Appzweck separat vorbereitet. Keine Adapter-Audience/Scopes implementiert. |
| `router/auth_router.py` | CSRF-geschützter POST-Logout, lokale Löschung vor IdP-Logout übernommen. Eigenständige kleine Bestätigungsseite. |
| `web/proxy.py` | Bestehender Proxy untersucht: puffert Requests, streamt Antworten, filtert Header, besitzt geteilten HTTPX-Client. Nicht übernommen: in Phase 1 genügt der geschützte Testendpunkt. Cookie-Jar-Risiko wird nicht in einen neuen Proxy kopiert. |
| `context.py`, `web/deps.py`, `service/session_dto.py`, `web/views.py` | Enge Kopplung von Session, Schlüsseln, Registry und UI. Kein Import dieser Klassen; im neuen Dienst eigene Komposition ohne Portal-Abhängigkeit. |
| Golden-Master-SDKs | Header/RS256/kid/iss/aud/sub/roles/iat/exp/v-Vertrag berücksichtigt. Keine Änderung ihrer Dateien. Vollständige App-Kompatibilität und Navigation bleiben spätere Integrationsstufe. |

## Bewusste Grenzen

* Kein zweiter Login im Portal: dieser Dienst wird vorerst nur unabhängig getestet.
* Kein allgemeiner HTTP-Proxy oder Token-Signier-API ohne Autorisierung.
* Kein Access-/Refresh-Token an den Mock; ID-Token ausschließlich Redis/Logout.
* Mock verifiziert Signatur, Issuer, Audience und Zweck mit öffentlichem Schlüssel.
* Sessions haben standardmäßig fünf Minuten Idle-TTL und fünf Minuten absolute
  Laufzeit. Touch verlängert nur den Idle-TTL; JWTs sind 60 Sekunden gültig.
* Keine dynamische Audience-Auswahl aus Browserparametern.
* HTTP-Loopback ist ausschließlich lokale Entwicklung. Vor öffentlichem Betrieb
  sind TLS, Rate Limits, Secretbetrieb, Proxy-Trust, Netz-/Originisolation und
  die Integrationstests zwingend zu ergänzen/abzunehmen.

## Spätere Portaländerungen (noch nicht durchgeführt)

1. Portal-Session-Abhängigkeiten durch verifizierten UserContext ersetzen.
2. Vom Gateway kurzlebigen signierten Kontext für die dedizierte Portal-Audience
   erhalten; App-Assertions dürfen keine Portal-Adminrechte verleihen.
3. Portal-eigenes OIDC, Redis und private Schlüssel beim Umschalten entfernen.
4. Erst dann geschützte Weiterleitung/Registry-Policy synchronisieren.
5. Navigation, Logout, Fehlerseiten und App-Origins in getrennten Verträgen
   integrieren. Für unvertrauenswürdige Apps Browser- und Netzwerkgrenzen ergänzen.

Neue Laufzeitdateien ausschließlich unter `awp-hka-security-gateway`; generierte
Zugangsdaten/Schlüssel ausschließlich im externen lokalen Secretverzeichnis.

## Korrektur: vorhandenen IdP wiederverwenden

Der zunächst angelegte Demo-Realm wurde entfernt. Compose enthält ausschließlich
Gateway und eigenen Redis und hängt den Gateway an ein explizit angegebenes
bestehendes Keycloak-Netz. Der Starthelfer erzeugt nur den Signaturschlüssel,
keine IdP-Secrets oder Benutzer. Netzwerkname, externer Secretpfad und die
Callback-/Logoutfreigabe sind durch den Betreiber zu bestätigen. Der Live-Zustand
ist nicht verifiziert. Keine automatische Anpassung oder Rücksetzung des IdP.

## Redis-Store als gemeinsame Ausgangsbasis

Die frühere vereinfachte Klasse `Sessions` wurde entfernt. Gateway-Aufrufe,
Assertions und Tests arbeiten mit dem aus dem Portal übernommenen `Session`-Modell.
Das Portal selbst wurde nicht verändert. Änderungen gegenüber der Portalbasis:
Import auf lokale Modelle, Standardlogging, injizierbare Uhr, v2-Namespace und das
abgeleitete absolute `expires_at` für `/me`. Kein Lua/CAS, keine neuen Sperr- oder
Rollenmechanismen. Die bekannte Touch-/Logout-Race bleibt ausdrücklich offen.

| Verhalten | Portal | Früherer Gateway | Gateway nach Übernahme |
|---|---|---|---|
| Sessiondaten | Hash | JSON-String | Hash |
| Inaktivitäts-TTL | ja | feste TTL ohne Touch | ja |
| Absolute Laufzeit | Prüfung beim Lesen | Prüfung beim Lesen | wie Portal |
| Touch-Drosselung | ja | nein | ja |
| Benutzerindex | Set | keiner | Set |
| Einzelne Session löschen | Hash + Index | String löschen | Hash + Index |
| Login-Transaktion | RedisLoginStore, GETDEL | vereinfachte Kombiklasse | RedisLoginStore, GETDEL |
| Speicherfallback | optional im Portal-Kontext | keiner | keiner |

Die Namespaceversion wird wegen des geänderten Redis-Datentyps erhöht; erneute
Gateway-Anmeldung erforderlich. Altbestände werden nicht aktiv verändert.
