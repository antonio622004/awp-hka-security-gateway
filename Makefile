# Same Python workflow as the portal; no UI/SDK build steps.
.PHONY: setup test

setup:
	uv sync

test:
	uv run pytest -q tests
