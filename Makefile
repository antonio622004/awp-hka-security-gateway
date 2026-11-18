# Same Python workflow as the portal; no UI/SDK build steps.
.PHONY: setup test keycloak-theme-update server-init server-up server-down vm-images vm-images-ghcr vm-check

setup:
	uv sync

test:
	uv run pytest -q tests

# Kit-Kopie für das Keycloak-Login-Theme (keycloak/theme-kit/) aus dem Portal übernehmen und prüfen.
# Im Portal-Repository vorher: make keycloak-theme-release
# Aufruf: make keycloak-theme-update THEME_DIST=<Portal-Repository>/sdk/dist/keycloak-theme
keycloak-theme-update:
	uv run python tools/keycloak_theme.py update $(THEME_DIST)

# Lokaler Gesamtstart (server/compose.yml): Gateway, Redis, Keycloak, Portal, Adapter.
# Gateway http://localhost:18080, Keycloak http://localhost:8180
# Einmalig vorher: server/.env, Secrets in server/.secrets/ und Portal-Ordner anlegen (überschreibt nichts).
server-init:
	uv run python tools/server_init.py

server-up:
	docker compose -f server/compose.yml up -d --build

server-down:
	docker compose -f server/compose.yml down

# Test-VM (vm/compose.yml, docs/vm.md). Auf der VM wird nicht gebaut: Images hier mit den VM-Werten bauen
# (Tags, gehärtetes Portal-Dockerfile; braucht docker login dhi.io) und als EINE Datei speichern.
VM_ENV ?= vm/.env.example
VM_IMAGES ?= build/hka-vm-images.tar.gz
VM_COMPOSE = docker compose -f vm/compose.yml --env-file $(VM_ENV)
# Redis per Digest aus redis/compose.yml (leeres REDIS_IMAGE: dort gilt der Standardwert); auf der VM heißt es wie
# in $(VM_ENV), weil docker save Digest-Namen nicht mitnimmt.
REDIS_PIN = REDIS_IMAGE= docker compose -f redis/compose.yml config --images
VM_REDIS = \
	docker pull --platform linux/amd64 $$($(REDIS_PIN)) && \
	docker tag $$($(REDIS_PIN)) $$($(VM_COMPOSE) config --images gateway-redis)

vm-images:
	$(VM_COMPOSE) build --pull
	$(VM_REDIS)
	mkdir -p $(dir $(VM_IMAGES))
	docker save --platform linux/amd64 $$($(VM_COMPOSE) config --images) | gzip > $(VM_IMAGES)
	@echo "Gespeichert: $(VM_IMAGES)"

# Wie vm-images, aber Portal und Keycloak kommen fertig aus GHCR (Pipeline nach Merge auf main, HKA-57).
# Aufruf: make vm-images-ghcr PORTAL_REF=ghcr.io/alexandru-tatar/portal@sha256:… KEYCLOAK_REF=ghcr.io/antonio622004/keycloak@sha256:…
# Die Digests stehen in der Zusammenfassung des Pipeline-Laufs. Die Images bekommen die Namen aus $(VM_ENV)
# (hka/portal:<PORTAL_IMAGE_TAG>, hka/keycloak:<KEYCLOAK_IMAGE_TAG>); vm/compose.yml und deploy.env bleiben gleich.
# Gateway und Adapter werden weiter hier gebaut. Sind die Pakete privat: vorher docker login ghcr.io.
vm-images-ghcr:
	@test -n "$(PORTAL_REF)" && test -n "$(KEYCLOAK_REF)" \
	  || { echo "PORTAL_REF und KEYCLOAK_REF fehlen (Digests aus dem Pipeline-Lauf)"; exit 1; }
	docker pull --platform linux/amd64 $(PORTAL_REF)
	docker tag $(PORTAL_REF) $$($(VM_COMPOSE) config --images backend)
	docker pull --platform linux/amd64 $(KEYCLOAK_REF)
	docker tag $(KEYCLOAK_REF) $$($(VM_COMPOSE) config --images keycloak)
	$(VM_COMPOSE) build --pull gateway adapter
	$(VM_REDIS)
	mkdir -p $(dir $(VM_IMAGES))
	docker save --platform linux/amd64 $$($(VM_COMPOSE) config --images) | gzip > $(VM_IMAGES)
	@echo "Gespeichert: $(VM_IMAGES)"

# vm/compose.yml mit den Werten aus vm/.env.example prüfen (startet nichts, braucht keine Secrets).
vm-check:
	$(VM_COMPOSE) config --quiet
	@echo "OK: vm/compose.yml mit $(VM_ENV)"
	$(VM_COMPOSE) config --services
	$(VM_COMPOSE) config --images
