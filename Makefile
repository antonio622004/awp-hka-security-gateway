# Same Python workflow as the portal; no UI/SDK build steps.
.PHONY: setup test keycloak-theme-update server-init server-up server-down vm-images vm-check

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

vm-images:
	$(VM_COMPOSE) build --pull
	docker pull --platform linux/amd64 redis:8-alpine
	mkdir -p $(dir $(VM_IMAGES))
	docker save $$($(VM_COMPOSE) config --images) | gzip > $(VM_IMAGES)
	@echo "Gespeichert: $(VM_IMAGES)"

# vm/compose.yml mit den Werten aus vm/.env.example prüfen (startet nichts, braucht keine Secrets).
vm-check:
	$(VM_COMPOSE) config --quiet
	@echo "OK: vm/compose.yml mit $(VM_ENV)"
	$(VM_COMPOSE) config --services
	$(VM_COMPOSE) config --images
