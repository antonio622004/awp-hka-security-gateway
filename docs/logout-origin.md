# Logout: 403 Foreign Origin (2026-11-10)

## Ursache und kleinster Fix

Die Middleware setzte auch auf der Logout-Bestätigungsseite
`Referrer-Policy: no-referrer`. Bei einem nicht-CORS Formular-POST setzt der
Browser damit gemäß [Fetch-Standard](https://fetch.spec.whatwg.org/#append-a-request-origin-header)
`Origin: null`. Das passt nicht zu `GW_PUBLIC_URL=http://localhost:18080` und
wird vom Logout-Handler mit 403 abgelehnt. GET funktioniert, weil dort diese
POST-Herkunftsprüfung noch nicht erfolgt.

Nur `GET /logout` erhält jetzt `Referrer-Policy: same-origin`. Die übrigen
Antworten, insbesondere OIDC und Redirects, behalten `no-referrer`. Keine
Änderung an Origin-Vergleich, Sec-Fetch-Site-Prüfung, CSRF-Token, Sessions,
Dockerkonfiguration oder `proxy.is_same_origin()`. Insbesondere wird `Origin:
null` nicht freigegeben; die eigene Formularseite unterdrückt ihre Origin nicht
mehr. Ein Ersetzen durch die allgemeinere Proxyprüfung wäre keine notwendige
Lösung dieses Fehlers.

## Regressionen und Nachweis

Die neue Formular-Regression scheiterte vor der Änderung am falschen
Referrer-Policy-Header. Nach der Änderung:

* 12 Logout-Tests erfolgreich: erfolgreiche Abmeldung mit Browserheadern,
  Cookie-/Sessioninvalidierung, falsches CSRF, fremde Origin, anderer Port,
  anderes Schema, `null` und widersprüchliche Fetch-Metadata.
* Gesamte Gateway-Suite: **68 Tests und 50 Subtests bestanden**.

Der normale TestClient-Lauf blieb in dieser Sandbox beim Thread-/Eventloop-
Handshake hängen. Für die Testausführung wurde ausschließlich im temporären
Testprozess `/tmp/hka-logout-pytest-runner.py` eine periodisch aufwachende
Selector-Loop verwendet. So werden die vorhandenen TestClient-Callbacks trotz
blockierter Socket-Wakeups verarbeitet. Kein Netzwerkzugriff wurde freigeschaltet,
keine Anwendung/Assertions/Sicherheitsprüfungen gemockt oder deaktiviert. Diese
Umgebungsanpassung ist nicht Teil der Projektdateien. Zwei Warnungen betrafen
pytest-Import-Rewriting im Runner und einen bestehenden HTTPX2-Aufruf.

Docker-Build/Neustart war wegen verweigertem Docker-Socketzugriff nicht möglich.
Der tatsächliche Origin-Header des gemeldeten Browserrequests wurde hier nicht
aufgezeichnet. Nach Neubau des Gateway-Images die Bestätigungsseite neu laden
und den echten Browserlogout nochmals prüfen; keine alte Formularseite verwenden.
Portal, Keycloak und Adapter wurden nicht geändert. Keine Commits.
