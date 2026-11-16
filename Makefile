# Same Python workflow as the portal; no UI/SDK build steps.
.PHONY: setup test keycloak-theme-update

setup:
	uv sync

test:
	uv run pytest -q tests

# Kit-Kopie für das Keycloak-Login-Theme (keycloak/theme-kit/) aus dem Portal übernehmen und prüfen.
# Im Portal-Repository vorher: make keycloak-theme-release
# Aufruf: make keycloak-theme-update THEME_DIST=<Portal-Repository>/sdk/dist/keycloak-theme
keycloak-theme-update:
	@test -n "$(THEME_DIST)" || { echo "THEME_DIST fehlt: make keycloak-theme-update THEME_DIST=<Portal>/sdk/dist/keycloak-theme"; exit 1; }
	uv run python tools/keycloak_theme.py update $(THEME_DIST)
