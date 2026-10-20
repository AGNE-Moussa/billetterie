# billetterie

Plateforme de vente de billets pour concerts et spectacles : microservices Python 3.12 / FastAPI,
PostgreSQL, Redis, RabbitMQ, Consul, Traefik et Keycloak, front React dans `frontend/`.

## Documentation

- [Conception](docs/conception.md) : vision, microservices, règles métier, flux critique, pannes,
  API partenaires
- [Conventions](docs/conventions.md) : contrats, routes, erreurs, données, événements
- [ADR-001 : pile technique](docs/adr/001-pile-technique.md) : pourquoi FastAPI, Consul,
  Traefik, Keycloak et RabbitMQ

## Démarrer

Prérequis : [uv](https://docs.astral.sh/uv/), Docker, GNU Make.

```sh
uv sync          # installe Python 3.12 si besoin et l'environnement de développement
cp .env.example .env
make init        # active les hooks Git (refus des messages hors Conventional Commits)
make help        # liste les commandes disponibles
make up          # démarre la plateforme locale
```

## Accès locaux

Après `make up`, tout est publié sur la machine locale uniquement. La gateway sert un seul
domaine, `http://localhost`, pour l'API, l'authentification et (plus tard) le front :

| Composant | Adresse |
|---|---|
| API Gateway (point d'entrée de l'API) | http://localhost/api/v1/... |
| Keycloak, realm `billetterie` | http://localhost/auth/realms/billetterie |
| Console d'administration Keycloak | http://localhost/auth/admin (`KEYCLOAK_ADMIN` du `.env`) |
| Tableau de bord Traefik | http://127.0.0.1:8080/dashboard/ |
| Consul (registre de services) | http://127.0.0.1:8500 |
| RabbitMQ (interface de gestion) | http://127.0.0.1:15672 |
| Mailpit (boîte de réception de test) | http://127.0.0.1:8025 |
| PostgreSQL / Redis | `127.0.0.1:5432` / `127.0.0.1:6379` |

Utilisateurs de test du realm (mots de passe dans le `.env`) : `client.test` (rôle `customer`),
`partenaire.test` (`partner`), `admin.test` (`admin`).

L'API exige un jeton Keycloak (`Authorization: Bearer ...`) : sans jeton valide, la gateway
répond 401 sans appeler le service. Les routes ouvertes sans jeton se déclarent dans
`ROUTES_PUBLIQUES` (voir `infra/verificateur/README.md`).

## Structure

```text
.claude/             outillage Claude (rules, agents, skills, hooks)
.github/workflows/   CI, déploiement, GitHub Pages
docs/                conception, ADR, contrats, plans de test, reviews, tickets
infra/               postgres, traefik, consul, keycloak, rabbitmq, grafana, verificateur
libs/commun/         code partagé entre les services
services/            microservices FastAPI
frontend/            application React
tests/smoke/         smoke tests de la plateforme
postman/             collections et scénarios de panne
```

## Règles de contribution

Aucun push direct sur `main` : une branche par ticket, une pull request, CI verte avant fusion.
