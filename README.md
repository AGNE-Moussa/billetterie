# billetterie

Plateforme de vente de billets pour concerts et spectacles : microservices Python 3.12 / FastAPI,
PostgreSQL, Redis, RabbitMQ, Consul, Traefik et Keycloak, front React dans `frontend/`.

## Démarrer

Prérequis : [uv](https://docs.astral.sh/uv/), Docker, GNU Make.

```sh
uv sync          # installe Python 3.12 si besoin et l'environnement de développement
cp .env.example .env
make help        # liste les commandes disponibles
```

## Structure

```text
.claude/             outillage Claude (rules, agents, skills, hooks)
.github/workflows/   CI, déploiement, GitHub Pages
docs/                conception, ADR, contrats, plans de test, reviews, tickets
infra/               traefik, consul, keycloak, rabbitmq, grafana, verificateur
libs/commun/         code partagé entre les services
services/            microservices FastAPI
frontend/            application React
tests/smoke/         smoke tests de la plateforme
postman/             collections et scénarios de panne
```

## Règles de contribution

Aucun push direct sur `main` : une branche par ticket, une pull request, CI verte avant fusion.
