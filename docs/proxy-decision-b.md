# Entscheidung B: gezielte Proxykorrekturen und App-Routen

> **Historisch.** Zwischenstand der Migration (November 2026), nicht mehr gepflegt. Erwähnte Dateien wie
> `compose.yml` (Phase 1), `compose.portal.yml`, `compose.registry.yml`, `compose.vm.yml`, `deployment/` oder
> `tools/dev.py` gibt es nicht mehr. Aktuell: [README](../README.md), [Gateway–Portal](gateway-portal.md),
> [VM](vm.md).

Nur der separate Gateway wurde geändert; das Portal einschließlich der vorherigen
Registry-API-Erweiterung bleibt gegenüber dem Beginn dieser Aufgabe unverändert.

## Genau zwei Sicherheitsabweichungen vom ursprünglichen Portalproxy

1. `proxy.DROPPED_REQUEST` enthält zusätzlich `authorization`. Eingehende
   Authorization-Header werden unabhängig von Groß-/Kleinschreibung entfernt.
   Die aus Session und autorisiertem Appdeskriptor erzeugte `X-Portal-Assertion`
   ersetzt wie bisher jede mitgeschickte Assertion.
2. Der gemeinsame HTTPX-Client verwendet `CookieJar(policy=RejectCookies())`.
   Die Policy lehnt das Speichern von Antwortcookies und deren Rückgabe ab.
   Es werden keine Micro-App-Cookies im Clientjar angesammelt. Insbesondere kein
   `cookies.clear()` zwischen Requests: parallele Requests teilen keinen durch
   Löschzeitpunkte unsicher gewordenen Benutzerzustand. Das bisherige Filtern von
   Browser-`Cookie` und Response-`Set-Cookie` bleibt zusätzlich erhalten.

Pfad und Query bleiben unverändert, Requestbodies bleiben begrenzt gepuffert,
Antworten werden weiter gestreamt. Methoden, Timeout-/Fehlerzuordnung,
Location-Umschreibung, Responseheaderfilter und Origin-Prüfung wurden nicht verändert.
Keine zusätzlichen Protokolle, Sicherheitskorrekturen oder Adapterfunktionen.

## Verbundener Ablauf

`GET /apps/{slug}` gibt wie im Portal 308 auf den abschließenden Slash zurück.
`/apps/{slug}/{path}` unterstützt GET, HEAD, POST, PUT, PATCH, DELETE und OPTIONS:

1. Session aus Redis laden.
2. Bestehenden `AppService.find_authorized()` aufrufen. Sein Reader fragt die
   Portal-API ohne Cache ab. Unbekannt/nicht geroutet → 404, keine Session → Login,
   Rolle fehlt → 403, nicht gesund → 503. Registry-/Redis-Ausfall → 503.
3. Für schreibende Methoden die unverändert übernommene Origin-Prüfung ausführen.
4. Vorhandene `Assertions.mint_app()` verwenden, einschließlich Rollenfilter,
   `aud`, `azp` und Adapter-`scp`. Keine Token aus Browserheadern übernehmen.
5. Über den korrigierten `AppProxy` weiterleiten.

Redis, synchroner Registry-HTTP-Client und JWT-Signierung laufen in FastAPIs
Threadpool, die asynchrone HTTP-Weiterleitung im Eventloop. Beim Shutdown wird
der Gateway-eigene Proxyclient geschlossen. Keine Registrykopie oder Policiespeicherung.

## Konfiguration und verbleibende Integrationsgrenzen

Zusätzlich zur Registry-Konfiguration aus [internal-registry.md](internal-registry.md)
ist `GW_APP_UPSTREAM` notwendig, etwa `http://app-{slug}:8080` entsprechend der
bestehenden Portal-Konvention. Die opt-in Datei `compose.registry.yml` reicht den
Wert weiter; ohne Wert wird kein Proxyclient angelegt. Appaufrufe ohne konfigurierte
Registry oder ohne Upstream antworten mit 503. Login-/Demo-Endpunkte bleiben nutzbar.
Die Defaults für Proxytimeouts und Bodylimit entsprechen dem Portal (2 s Connect,
30 s Read, 10 MiB Body); Tests können `Settings.apps=AppsConfig(...)` injizieren.

Vor echtem Betrieb müssen Gateway→App-Netzwerkerreichbarkeit und die bereits
vorgesehenen Rollenmapping-/Rollenvokabular-Einstellungen bereitstehen. Die
Micro-App erwartet wie bisher den vollständigen Pfad `/apps/<slug>/…`.
Keine laufenden Compose-/VM-Dienste oder Netzwerke wurden verändert.

Unverändert bleiben die schon dokumentierten Grenzen (unter anderem einfacher
Location-Präfixvergleich, Connection-Header-Grenzen, gemeinsame Browser-Origin).
Auch die bestehende globale Gateway-CSP wurde nicht abgeschwächt: sie kann
Scripts/Styles weitergeleiteter Appseiten blockieren. Deren Richtlinienintegration
und ein Browsernachweis bleiben separat; diese Aufgabe ändert ausschließlich
die zwei freigegebenen Proxyprobleme und die notwendige Verdrahtung.

## Nachweis

Erfolgreich: insgesamt 38 bestehende/neue ausführbare Tests, darunter sechs neue
Proxytests mit echtem HTTPX 0.28.1, Starlette und MockTransport:

* keine Authorization-/Browser-Cookie-Weitergabe und keine gefälschte Assertion;
* kein Speichern/Wiederverwenden von Hostcookies bei weiteren Benutzern;
* keine Domaincookies über mehrere Upstreams;
* zwölf parallele Requests ohne gemeinsame Cookies;
* bestehendes Pfad-/Query-/Body-/Location-Verhalten;
* bestehendes Bodylimit und 502-/503-/504-Fehlerverhalten.

Die Proxytests führen den tatsächlichen Proxyquelltext mit isolierten Imports
und den echten Starlette-Klassen hinter den FastAPI-Reexports aus; keine HTTPX-
oder StreamingResponse-Attrappe. Der Logger ist isoliert. Die benötigten reinen
Pythonpakete wurden lesend aus der vorhandenen lokalen Umgebung geladen; keine
Golden-Master-Dateien oder Pakete wurden geändert. Ruff und Syntaxprüfung erfolgreich.

Zusätzlich ergänzt, aber hier nicht ausführbar: FastAPI-HTTP-Integrationstests in
`test_app.py` für die echten App-Routen, Assertionprüfung am Mock-Upstream,
ungecachte Rollen-/Statusänderungen, Verweigerung ohne Upstreamzugriff,
Redis-/Registryfehler, Sessionablauf, Origin-Sperre und unterstützte Methoden.
In der Systemumgebung fehlt pytest; die verfügbaren weiteren Pakete sind nicht
vollständig bzw. kompatibel für einen FastAPI-Gesamtlauf. Kein echter IdP-,
Redis-, Browser-, Container- oder VM-Test wird als erfolgreich behauptet.
