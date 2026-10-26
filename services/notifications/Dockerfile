# Image du service notifications, à construire depuis la racine du dépôt :
#   docker build -f services/notifications/Dockerfile .
# Même structure que l'image du service modèle (services/echo/Dockerfile).

# --- Étape 1 : environnement Python construit avec uv --------------------------------------
FROM python:3.12.12-slim AS construction

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /depot

# Dépendances d'abord : cette couche reste en cache tant que uv.lock ne change pas.
# uv lit les pyproject.toml de tous les membres du workspace pour valider uv.lock.
COPY pyproject.toml uv.lock ./
COPY libs/pyproject.toml libs/
COPY services/echo/pyproject.toml services/echo/
COPY services/catalogue/pyproject.toml services/catalogue/
COPY services/billets/pyproject.toml services/billets/
COPY services/commandes/pyproject.toml services/commandes/
COPY services/paiements/pyproject.toml services/paiements/
COPY services/notifications/pyproject.toml services/notifications/
COPY infra/verificateur/pyproject.toml infra/verificateur/
RUN uv sync --locked --no-dev --package billetterie-notifications --no-install-workspace

# Puis le code du workspace, installé dans l'environnement (non éditable).
COPY libs libs
COPY services/notifications services/notifications
RUN uv sync --locked --no-dev --package billetterie-notifications --no-editable

# --- Étape 2 : image finale, sans uv ni sources ---------------------------------------------
FROM python:3.12.12-slim

RUN useradd --create-home --uid 10001 service
WORKDIR /app

COPY --from=construction /app/.venv /app/.venv
# Migrations : lancées par le conteneur notifications-migrations du compose.
COPY services/notifications/alembic.ini ./alembic.ini
COPY services/notifications/alembic ./alembic

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER service
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "--factory", "notifications.principal:creer_app", "--host", "0.0.0.0", "--port", "8000"]
