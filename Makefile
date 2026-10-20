# Raccourcis de développement du projet billetterie.
# Les recettes doivent être indentées par une tabulation.

.DEFAULT_GOAL := help
.PHONY: help init up down reset test test-unit test-integration lint typecheck

# Dossiers de tests de chaque service (et du vérificateur), trouvés par make (portable sous Windows).
TESTS_UNITAIRES := tests/unit $(wildcard services/*/tests/unit) $(wildcard infra/*/tests/unit)
TESTS_INTEGRATION := tests/integration $(wildcard services/*/tests/integration)

help:
	@echo Cibles disponibles :
	@echo   init              active les hooks Git du projet (.githooks)
	@echo   up                demarre la plateforme locale (Docker Compose)
	@echo   down              arrete la plateforme locale
	@echo   reset             arrete la plateforme et efface ses donnees (volumes)
	@echo   test              lance tous les tests (pytest)
	@echo   test-unit         tests unitaires, rapides, sans Docker
	@echo   test-integration  tests d'integration (Testcontainers, Docker requis)
	@echo   lint              verifie le style et le formatage (ruff)
	@echo   typecheck         verifie le typage strict (mypy)

init:
	git config core.hooksPath .githooks

up:
	docker compose up -d --wait

down:
	docker compose down

reset:
	docker compose down --volumes

test:
	uv run pytest

test-unit:
	uv run pytest $(TESTS_UNITAIRES)

test-integration:
	uv run pytest $(TESTS_INTEGRATION)

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy
