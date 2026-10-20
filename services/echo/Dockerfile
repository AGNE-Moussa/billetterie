# Image du service echo, à construire depuis la racine du dépôt :
#   docker build -f services/echo/Dockerfile .
# Modèle des images des services : même structure, seul le nom du paquet change.

# --- Étape 1 : environnement Python construit avec uv --------------------------------------
FROM python:3.12.12-slim AS construction

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /depot

# Dépendances d'abord : cette couche reste en cache tant que uv.lock ne change pas.
COPY pyproject.toml uv.lock ./
COPY libs/pyproject.toml libs/
COPY services/echo/pyproject.toml services/echo/
COPY infra/verificateur/pyproject.toml infra/verificateur/
RUN uv sync --locked --no-dev --package billetterie-echo --no-install-workspace

# Puis le code du workspace, installé dans l'environnement (non éditable).
COPY libs libs
COPY services/echo services/echo
RUN uv sync --locked --no-dev --package billetterie-echo --no-editable

# --- Étape 2 : image finale, sans uv ni sources ---------------------------------------------
FROM python:3.12.12-slim

RUN useradd --create-home --uid 10001 service
WORKDIR /app

COPY --from=construction /app/.venv /app/.venv
# Migrations : lancées par le conteneur echo-migrations du compose.
COPY services/echo/alembic.ini ./alembic.ini
COPY services/echo/alembic ./alembic

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER service
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "--factory", "echo.principal:creer_app", "--host", "0.0.0.0", "--port", "8000"]
