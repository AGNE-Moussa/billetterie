# Raccourcis de développement du projet billetterie.
# Les recettes doivent être indentées par une tabulation.

.DEFAULT_GOAL := help
.PHONY: help init up down test lint typecheck

help:
	@echo Cibles disponibles :
	@echo   init       active les hooks Git du projet (.githooks)
	@echo   up         demarre la plateforme locale (Docker Compose)
	@echo   down       arrete la plateforme locale
	@echo   test       lance les tests (pytest)
	@echo   lint       verifie le style et le formatage (ruff)
	@echo   typecheck  verifie le typage strict (mypy)

init:
	git config core.hooksPath .githooks

up:
	docker compose up -d

down:
	docker compose down

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy services libs
