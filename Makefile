# Raccourcis de développement du projet billetterie.
# Les recettes doivent être indentées par une tabulation.

.DEFAULT_GOAL := help
.PHONY: help init up observabilite pannes down reset test test-unit test-integration test-smoke lint typecheck

# Dossiers de tests de chaque service (et du vérificateur), trouvés par make (portable sous Windows).
TESTS_UNITAIRES := tests/unit $(wildcard services/*/tests/unit) $(wildcard infra/*/tests/unit)
TESTS_INTEGRATION := tests/integration $(wildcard services/*/tests/integration)

help:
	@echo Cibles disponibles :
	@echo   init              active les hooks Git du projet (.githooks)
	@echo   up                demarre la plateforme locale (Docker Compose)
	@echo   observabilite     demarre la plateforme avec Prometheus et Grafana (http://127.0.0.1:3000)
	@echo   pannes            rejoue les scenarios de panne (docs/pannes-infra.md), plateforme demarree
	@echo   down              arrete la plateforme locale (observabilite comprise)
	@echo   reset             arrete la plateforme et efface ses donnees (volumes)
	@echo   test              lance tous les tests (pytest)
	@echo   test-unit         tests unitaires, rapides, sans Docker
	@echo   test-integration  tests d'integration (Testcontainers, Docker requis)
	@echo   test-smoke        smoke tests contre la plateforme demarree (make up)
	@echo   lint              verifie le style et le formatage (ruff)
	@echo   typecheck         verifie le typage strict (mypy)

init:
	git config core.hooksPath .githooks

up:
	docker compose up -d --wait

observabilite:
	docker compose --profile observabilite up -d --wait

pannes:
	bash scripts/pannes.sh tous

down:
	docker compose --profile observabilite down

reset:
	docker compose --profile observabilite down --volumes

test:
	uv run pytest

test-unit:
	uv run pytest $(TESTS_UNITAIRES)

test-integration:
	uv run pytest $(TESTS_INTEGRATION)

test-smoke:
	uv run pytest tests/smoke -m smoke

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy
