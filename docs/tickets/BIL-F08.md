# BIL-F08 : Service echo de référence (squelette FastAPI)

- **Branche** : `feat/bil-f08-service-echo`
- **Dépend de** : BIL-F07

## Objectif

Créer `services/echo`, un service minimal qui sert de modèle à tous les services métier et de
cobaye pour le workflow.

## Étapes

- [x] 1. Arborescence type : `src/echo/` (api, domaine, infra), `alembic/`, `tests/unit/`,
  `tests/integration/`, `openapi.yaml`, `Dockerfile` multi-étapes
- [x] 2. Routes `GET /health` et `GET /api/v1/echos/{message}` ; une table `echos`
  (ajout décidé : `POST /api/v1/echos`, pour ne pas écrire en base dans un GET)
- [x] 3. Configuration par Pydantic Settings ; enregistrement Consul au démarrage
- [x] 4. Deux instances dans le compose pour vérifier le load balancing
- [x] 5. Tests unitaires et d'intégration (Testcontainers PostgreSQL) ; test de contrat activé
  dans la CI

## Critères d'acceptance

- [x] CA1 : `GET /api/v1/echos/bonjour` répond via Traefik, alternativement par les deux
  instances (5 réponses `echo-1`, 5 réponses `echo-2`)
- [x] CA2 : le test de contrat échoue si une route diverge de `openapi.yaml`
- [x] CA3 : l'image Docker se construit en amd64 et arm64 (amd64 en local, les deux dans le job
  `images` de la CI)

## Décisions

- `POST /api/v1/echos` ajouté ; base `echo` créée par le script d'initialisation ; `/health`
  vérifie la base (choix validés par le développeur).
