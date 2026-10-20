# Service echo : modèle des services métier

Service sans métier qui valide toute la chaîne : Consul, Traefik, PostgreSQL, migrations, tests.
**Chaque nouveau service reprend cette structure et ces conventions.**

## Routes

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/health` | Santé de l'instance et de sa base, appelée par Consul (non exposée par Traefik) |
| `POST` | `/api/v1/echos` | Enregistre un message (201, 409 `ECHO_EXISTANT`, 422 `REQUETE_INVALIDE`) |
| `GET` | `/api/v1/echos/{message}` | Relit un message et indique l'instance qui répond (404 `ECHO_INTROUVABLE`) |

Le contrat fait foi : `openapi.yaml`. Les erreurs sont au format Problem Details
(`application/problem+json`).

## Structure

```text
services/echo/
  openapi.yaml           contrat écrit d'abord, vérifié par tests/contract
  Dockerfile             multi-étapes (uv puis image finale non root), construit depuis la racine
  alembic.ini, alembic/  migrations (lancées par le conteneur echo-migrations)
  src/echo/
    config.py            Pydantic Settings : DATABASE_URL, INSTANCE, PORT, CONSUL_ACTIF
    principal.py         creer_app() : base, inscription Consul, routes
    api/                 routes, schémas, dépendances, erreurs Problem Details
    domaine/             règles et interface du dépôt, sans FastAPI ni SQLAlchemy
    infra/               SQLAlchemy 2 async, implémentation du dépôt
  tests/
    unit/                routes avec un dépôt en mémoire, sans Docker
    integration/         vraie base PostgreSQL (Testcontainers) et vraies migrations
    contract/            schéma généré contre openapi.yaml (pytest -m contract)
```

## Ajouter un service sur ce modèle

1. Copier la structure et renommer le paquet (`pyproject.toml`, `module-name`).
2. Ajouter sa base dans `infra/postgres/init/01-bases.sh` et son mot de passe dans `.env.example`.
3. Ajouter `services/<nom>/src` à `[tool.mypy] files` et le module à `known-first-party`.
4. Ajouter le service à la matrice du job `images` de la CI.
5. Déclarer dans le compose `<nom>-migrations` puis ses instances.
