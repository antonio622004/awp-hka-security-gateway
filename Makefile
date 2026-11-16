# Same Python workflow as the portal; no UI/SDK build steps.
.PHONY: setup test keycloak-theme-update server-init server-up server-down

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
