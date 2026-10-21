# Billetterie

Plateforme de vente de billets en microservices. Défi central : aucune place vendue deux fois
sous une charge extrême. Conception : `docs/conception.md`, choix de pile :
`docs/adr/001-pile-technique.md`.

## Pile

- Back-end : Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, workspace uv
- Données : PostgreSQL 16 (une base par service), Redis 7 (cache, verrous des places)
- Messages : RabbitMQ, exchange topic `ticketing`, via FastStream
- Infrastructure : Consul, Traefik v3, Keycloak (realm `billetterie`), Docker Compose
- Front : React, Vite, TypeScript dans `frontend/` (voir `frontend/CLAUDE.md`)

## Commandes

```sh
uv sync                    # installer l'environnement
make init                  # activer le hook commit-msg (.githooks/)
make up / make down        # démarrer (attend healthy) / arrêter la plateforme locale
make observabilite         # démarrer avec Prometheus et Grafana (profil Compose observabilite)
make pannes                # rejouer les scénarios de panne (docs/pannes-infra.md)
make reset                 # tout arrêter et effacer les volumes (rejoue l'init des bases)
make test                  # tous les tests (uv run pytest)
make test-unit             # tests unitaires (tests/unit et services/*/tests/unit), sans Docker
make test-integration      # tests d'intégration (Testcontainers, Docker requis)
make lint                  # ruff check + ruff format --check
make typecheck             # mypy strict
```

## Arborescence

```text
services/      microservices FastAPI      libs/commun/   code partagé (HTTP, auth, outbox)
infra/         postgres, traefik, consul, keycloak, rabbitmq, prometheus, tempo, grafana,
               verificateur
frontend/      application React          tests/smoke/   smoke tests de la plateforme
docs/          conception, conventions, adr/, contrats/, test-plans/, reviews/, tickets/
postman/       collections et scénarios de panne
.claude/       rules, agents, skills, hooks
```

Conventions (contrats, routes, erreurs, événements, données) : `docs/conventions.md`.
Modèle de tout nouveau service : `services/echo/` (voir son README).
Les règles détaillées par sujet vivent dans `.claude/rules/`, pas ici.

## Tickets dans Notion

- Board : `collection://628b2884-0d14-44a0-a153-8a844e530b8d` (propriété `Ticket ID`)
- Préfixe : `BIL-` (`BIL-F01` à `BIL-F29` pour les fondations, `BIL-001` et suivants pour le métier)
- Statuts (`Agile Statut`) : `🏁 SPRINT TODO` → `DOING` (début du ticket) → `IN REVIEW` (PR
  ouverte) → `TO TEST` → `✅ DONE` ; `BLOCKED` si une dépendance manque
- `TO TEST` et `✅ DONE` sont posés par le développeur
- Un ticket ne démarre que si tous ceux de `Dépend de` sont en `✅ DONE`
- Branche : celle de la propriété `Branche` du ticket

## Pipeline

- Un ticket = une branche = une PR ; `main` est protégée, aucun push direct.
- Commits en Conventional Commits, sans ligne d'attribution.
- Aucun agent ne merge, jamais : le développeur décide du merge.
- Une décision non prévue par le ticket remonte en question, elle n'est pas tranchée en silence.
- Si Notion est injoignable, s'arrêter plutôt qu'inventer le contenu d'un ticket.
