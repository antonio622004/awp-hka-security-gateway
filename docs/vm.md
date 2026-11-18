# Test-VM iwi-hean-05

Auf der VM läuft derselbe Stack wie lokal: Gateway, Redis, Keycloak, Portal-Backend und bwSync-Adapter in einem
Compose-Projekt (`hka-vm`, Datei `vm/compose.yml`), davor nginx mit HTTPS. Unterschiede zu lokal stehen nur in
`vm/.env` (Vorlage `vm/.env.example`): HTTPS-Adresse, Secure-Cookies, Keycloak unter `/auth`, Secrets und Daten
unter `/srv/portal/`, gehärtetes Portal-Image, feste Image-Tags.

**Auf der VM wird nicht gebaut** (sie erreicht keine Registry): Images auf dem eigenen Rechner bauen, als Datei
übertragen, auf der VM laden und mit `up -d --no-build` starten.

```text
Rechner: make vm-check, make vm-images ─► build/hka-vm-images.tar.gz ┐
         tar der Compose-Dateien      ─► build/hka-vm-files.tar.gz  ├─ scp ─► VM: docker load, tar -x, Secrets,
                                                                     ┘          alte Container stoppen, up --no-build
```

## Wichtig vorab

- **VM ohne Internet:** keine Registry, kein `pip`/`npm`, kein `docker build`. Alles kommt als Datei vom eigenen
  Rechner (Abschnitt 1).
- **UID 65532:** Das gehärtete Portal-Image läuft als `nonroot` mit UID 65532. Die Ordner
  `/srv/portal/{manifests,status,registry}` müssen dieser UID gehören (`extras/compose/vm/deploy/README.md` liest
  die UID aus dem Image). Gateway und Adapter laufen als UID 10001; ihre Secrets sind deshalb `0444` in einem
  `0700`-Ordner von root.
- **`/etc/portal/deploy.env`:** `PORTAL_IMAGE` muss auf das Portal-Image aus `vm/.env` zeigen, sonst prüft
  `portal-deploy` Manifeste mit einem alten Image (Abschnitt 5).
- **`bwsync-credentials.key` ist nötig:** Ohne ihn startet der Adapter nicht. Einmal anlegen, nie ersetzen, sobald
  bwSync-Zugänge gespeichert sind (Abschnitt 3).

## Ordnerstruktur auf der VM

```text
~/awp/                                      wie lokal nebeneinander, nur die Dateien, die Compose braucht
├── awp-hka-security-gateway/
│   ├── gateway/compose.yml  redis/compose.yml  keycloak/compose.yml  keycloak/hka-realm.json
│   └── vm/compose.yml  vm/.env.example  vm/.env (nur auf der VM, chmod 600)
├── awp-hka-intranet-portal/
│   ├── extras/compose/backend/compose.yml
│   ├── extras/compose/vm/nginx-portal.conf  extras/compose/vm/deploy/
│   └── dev/roles.yml
└── awp-hka-adapter/compose.yml

/srv/portal/
├── manifests/  status/  registry/          Portal-Daten (wie bisher, gehören der UID des Portal-Images)
└── gateway/
    ├── roles.yml                           Kopie von dev/roles.yml (IdP-Claims -> Rollen)
    └── secrets/  (0700, Dateien 0444)      oidc-client-secret, signing-key.pem, registry-service-token,
                                            bwsync-credentials.key
/etc/portal/deploy.env, /usr/local/sbin/portal-deploy     Apps registrieren (extras/compose/vm/deploy/README.md)
/etc/nginx/sites-available/portal                         = extras/compose/vm/nginx-portal.conf
```

## 1. Auf dem eigenen Rechner

Alle Repos auf dem Stand, der auf die VM soll, nebeneinander in `awp/`. Für das gehärtete Portal-Image einmal
`docker login dhi.io`.

```sh
cd awp/awp-hka-security-gateway
make vm-check        # vm/compose.yml mit vm/.env.example prüfen; listet Dienste und Images
make vm-images       # baut hka/security-gateway, hka/keycloak, hka/portal, hka/adapter mit den Tags aus
                     # vm/.env.example, holt redis:8-alpine -> build/hka-vm-images.tar.gz

# Compose-Dateien für ~/awp auf der VM (im Ordner awp/ aufrufen):
cd ..
tar -czf awp-hka-security-gateway/build/hka-vm-files.tar.gz \
  awp-hka-security-gateway/gateway/compose.yml awp-hka-security-gateway/redis/compose.yml \
  awp-hka-security-gateway/keycloak/compose.yml awp-hka-security-gateway/keycloak/hka-realm.json \
  awp-hka-security-gateway/vm/compose.yml awp-hka-security-gateway/vm/.env.example \
  awp-hka-intranet-portal/extras/compose/backend/compose.yml awp-hka-intranet-portal/extras/compose/vm \
  awp-hka-intranet-portal/dev/roles.yml awp-hka-adapter/compose.yml

scp awp-hka-security-gateway/build/hka-vm-images.tar.gz awp-hka-security-gateway/build/hka-vm-files.tar.gz \
  sadmin@iwi-hean-05.hs-karlsruhe.de:~
```

Neue Version: in `vm/.env.example` die Tags erhöhen (und `PORTAL_IMAGE` in `deploy.env.example` passend), dann
dieselben Schritte. Alte Images bleiben auf der VM und erlauben den Rückweg.

## 2. Auf der VM: laden und auspacken

```bash
gunzip -c ~/hka-vm-images.tar.gz | sudo docker load
sudo docker image ls 'hka/*'                 # Tags wie in vm/.env.example
install -d -m 0755 ~/awp && tar -xzf ~/hka-vm-files.tar.gz -C ~/awp
cd ~/awp/awp-hka-security-gateway
test -e vm/.env || install -m 0600 vm/.env.example vm/.env
```

Beim ersten Mal das Admin-Passwort von Keycloak in `vm/.env` setzen (ohne es anzuzeigen):

```bash
PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
sed -i "s/^KC_BOOTSTRAP_ADMIN_PASSWORD=.*/KC_BOOTSTRAP_ADMIN_PASSWORD=$PW/" vm/.env; unset PW
grep -c '^KC_BOOTSTRAP_ADMIN_PASSWORD=AUF-DER-VM-ERSETZEN' vm/.env    # muss 0 sein
```

## 3. Secrets und Rollen (einmalig; Vorhandenes nie überschreiben)

Vom bisherigen Gateway (`compose.vm.yml`) existieren schon `signing-key.pem`, `oidc-client-secret`,
`registry-service-token` und `roles.yml`; sie bleiben gültig. Neu ist nur der Schlüssel des Adapters. Jeder Befehl
legt eine Datei nur an, wenn sie fehlt, und gibt nichts aus:

```bash
sudo install -d -m 0700 /srv/portal/gateway/secrets
cd /srv/portal/gateway/secrets
sudo test -e signing-key.pem || sudo openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out signing-key.pem
sudo test -e registry-service-token || python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" \
  | sudo tee registry-service-token >/dev/null
sudo test -e bwsync-credentials.key || python3 -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(), end='')" \
  | sudo tee bwsync-credentials.key >/dev/null
# Secret des Clients "portal" aus dem Realm, den Keycloak importiert (Testwert, nur für Testdaten):
sudo test -e oidc-client-secret || python3 -c "import json; c = [c for c in json.load(open('$HOME/awp/awp-hka-security-gateway/keycloak/hka-realm.json'))['clients'] if c['clientId'] == 'portal'][0]; print(c['secret'], end='')" \
  | sudo tee oidc-client-secret >/dev/null
sudo chmod 0444 signing-key.pem registry-service-token bwsync-credentials.key oidc-client-secret
sudo ls -l /srv/portal/gateway/secrets       # vier Dateien, -r--r--r--
cd ~/awp/awp-hka-security-gateway

# Rollen: neue Fassung übernehmen, wenn sie sich unterscheidet
sudo diff ~/awp/awp-hka-intranet-portal/dev/roles.yml /srv/portal/gateway/roles.yml \
  || sudo install -m 0444 ~/awp/awp-hka-intranet-portal/dev/roles.yml /srv/portal/gateway/roles.yml
```

Den Adapter-Schlüssel nie ersetzen, sobald bwSync-Zugänge gespeichert sind (sonst sind sie unlesbar). Die
Portal-Ordner `/srv/portal/{manifests,status,registry}` gibt es schon (`extras/compose/vm/deploy/README.md`).

## 4. Alte Container stoppen

Bisher liefen zwei Projekte: `hka-gateway-vm` (Gateway, Redis, Portal aus `~/compose.vm.yml`) und `hka-portal-vm`
(Keycloak aus `~/compose.yml`); die Apps hingen im Netz `hka-portal-vm_default`. Erst ansehen, dann stoppen:

```bash
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Label "com.docker.compose.project"}}'
sudo docker compose -p hka-gateway-vm down
sudo docker compose -p hka-portal-vm down     # Netz bleibt, solange Apps daran hängen (Warnung ist normal)
```

`down` ohne `-v` löscht keine Volumes; Images und die alten Compose-Dateien in `~` bleiben für den Rückweg.
Achtung: Keycloak hatte kein Volume. Was in seiner Konsole von Hand geändert wurde (Benutzer, Clients), geht mit
`down` verloren; der neue Keycloak importiert den Realm aus dem Image. Wurde dort etwas geändert, vorher exportieren.

## 5. Starten

```bash
cd ~/awp/awp-hka-security-gateway
sudo docker compose -f vm/compose.yml config --quiet && echo ok
sudo docker compose -f vm/compose.yml up -d --no-build
sudo docker compose -f vm/compose.yml ps     # gateway und adapter "healthy"; Keycloak braucht 30–60 s
```

Apps in das neue Netz umhängen (je App; der Containername `app-<slug>` bleibt der Hostname):

```bash
sudo docker network connect hka-portal-apps app-<slug>
sudo docker network disconnect hka-portal-vm_default app-<slug>
sudo docker network rm hka-portal-vm_default   # wenn keine App mehr daran hängt
```

`portal-deploy` auf das neue Portal-Image stellen: in `/etc/portal/deploy.env` die Zeile
`PORTAL_IMAGE=hka/portal:<PORTAL_IMAGE_TAG aus vm/.env>` setzen (Vorlage: `extras/compose/vm/deploy/deploy.env.example`).
Das Image prüft Manifeste mit seiner eingebauten Konfiguration, z. B. den Scope `bwsync:delete`.

bwSync-Zugang für eine Person (fragt verdeckt nach `sub`, Anmeldename und App-Passwort):

```bash
sudo docker compose -f vm/compose.yml exec adapter python -m app.manage_credentials
```

## 6. nginx prüfen

Die laufende Konfiguration muss `extras/compose/vm/nginx-portal.conf` entsprechen (`/` → 127.0.0.1:18080,
`/auth/` → 127.0.0.1:8180, `/auth/admin/` 403, `/internal` 404, `X-Forwarded-*`):

```bash
sudo diff ~/awp/awp-hka-intranet-portal/extras/compose/vm/nginx-portal.conf /etc/nginx/sites-available/portal && echo gleich
# nur bei Unterschieden:
sudo install -m 0644 ~/awp/awp-hka-intranet-portal/extras/compose/vm/nginx-portal.conf /etc/nginx/sites-available/portal
sudo nginx -t && sudo systemctl reload nginx
```

## 7. Prüfbefehle

```bash
B=https://iwi-hean-05.hs-karlsruhe.de
curl -s -o /dev/null -w '%{http_code}\n' $B/                         # 302 (Anmeldung startet)
curl -s $B/auth/realms/hka/.well-known/openid-configuration \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['issuer'])"  # https://…/auth/realms/hka
curl -s -o /dev/null -w '%{http_code}\n' $B/.well-known/jwks.json     # 200
curl -s -o /dev/null -w '%{http_code}\n' $B/internal/apps/x/access    # 404
curl -s -o /dev/null -w '%{http_code}\n' $B/auth/admin/               # 403
sudo docker compose -f vm/compose.yml ps
sudo docker compose -f vm/compose.yml logs --tail 50 gateway backend keycloak
sudo portal-deploy list                                               # Apps mit Status, „Status vom …“ aktuell
```

Im Browser (privates Fenster): `https://iwi-hean-05.hs-karlsruhe.de/` → Anmeldeseite im Portal-Look → Portal ohne
Banner „Entwicklungsmodus“ → App im Menü → Abmelden ohne Zwischenseite. Keycloak-Konsole nur per Tunnel:
`ssh -L 8180:127.0.0.1:8180 sadmin@iwi-hean-05.hs-karlsruhe.de`, dann http://localhost:8180/auth/admin/.

## Zurück zum alten Stand

```bash
cd ~/awp/awp-hka-security-gateway && sudo docker compose -f vm/compose.yml down
sudo docker compose -f ~/compose.yml up -d --no-build        # alter Keycloak (hka-portal-vm)
sudo docker compose -f ~/compose.vm.yml up -d --no-build     # altes Gateway + Portal (hka-gateway-vm)
```

Danach die Apps wieder in `hka-portal-vm_default` hängen (`docker network connect`). Das neue Volume
`hka-adapter-data` bleibt dabei erhalten.
