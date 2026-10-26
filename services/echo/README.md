# Service echo : modèle des services métier

Service sans métier qui valide toute la chaîne : Consul, Traefik, PostgreSQL, migrations, tests.
**Chaque nouveau service reprend cette structure et ces conventions.**

## Routes

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/health` | Santé de l'instance et de sa base, appelée par Consul (echo ne l'expose pas par Traefik ; les services métier, si : voir ci-dessous) |
| `POST` | `/api/v1/echos` | Enregistre un message, scope `echos:write` (201, 403 `SCOPE_MANQUANT`, 409 `ECHO_EXISTANT`, 422 `REQUETE_INVALIDE`) |
| `GET` | `/api/v1/echos?page=&size=` | Liste paginée `EchoPage` `{elements, page, size, total}`, scope `echos:read` ; du plus récent au plus ancien, `page` ≥ 1 (1), `size` de 1 à 100 (20) ; page au-delà de la fin : `elements` vide (401 `JETON_*`, 403 `SCOPE_MANQUANT`, 422 `REQUETE_INVALIDE`) |
| `GET` | `/api/v1/echos/{message}` | Relit un message, appelant authentifié (401 `JETON_*`, 404 `ECHO_INTROUVABLE`) |

Le contrat fait foi : `openapi.yaml`. Les erreurs sont au format Problem Details
(`application/problem+json`), produites par `commun.erreurs` : une erreur métier est une
sous-classe d'`ErreurMetier(code, statut, détail)`. `commun.correlation` lit ou crée
`X-Correlation-Id` et écrit les journaux en JSON avec cet identifiant.

Droits : `commun.auth` revérifie la signature du jeton transmis par la gateway (jamais les seuls
en-têtes). Une route déclare ce qu'elle exige en une ligne :

```python
appelant: AppelantDep  # authentifié
appelant: Annotated[Appelant, Depends(exige_scopes("echos:write"))]  # scope
appelant: Annotated[Appelant, Depends(exige_role("admin"))]  # rôle
```

Santé via la gateway (services métier, BIL-001) : `commun.registre.tags_sante_traefik(nom,
ressource)`, ajouté aux tags de `tags_traefik`, déclare un second routeur
``Path(`/api/v1/<ressource>/health`) && Method(`GET`)`` réécrit en `/health` (`replacePath`),
de priorité explicite, sur la chaîne `standard@file` : un jeton est requis (401 sans jeton).
Exemple : `GET http://localhost/api/v1/seats/health` avec `Authorization: Bearer <jeton>`.

Dans les tests, `commun.faux_jetons.EmetteurDeTest` signe des jetons avec une clé de test :
`creer_app(config, verificateur_jetons=emetteur.verificateur())`, puis
`headers=emetteur.entetes(roles=[...], scopes=[...])`.

## Observabilité

`installer_observabilite(app, "echo")` (commun.observabilite) expose `/metrics` et trace
FastAPI et httpx ; `instrumenter_moteur(moteur)` trace les requêtes SQL. Prometheus trouve les
instances dans Consul (métadonnée `metriques` posée par commun.registre) ; les traces partent
vers Tempo (`OTEL_EXPORTER_OTLP_ENDPOINT`). Tableau de bord : `make observabilite`, puis
http://127.0.0.1:3000.

## Événements

Le POST publie `ticketing.echo.created` par l'outbox (`commun.outbox`) : l'événement est écrit
dans la table `outbox` dans la même transaction que l'echo, puis le relais (tâche de fond du
lifespan, activée par `RABBITMQ_URL`) le publie sur l'exchange `ticketing`. Le service écrit
même si RabbitMQ est arrêté ; les événements partent à son retour. Aucun code métier ne publie
directement sur RabbitMQ.

Un service qui consomme des événements utilise `commun.consommateurs.consommateur_idempotent`
(table `messages_traites`, trois tentatives puis `<file>.dlq`) et démarre ses consommateurs
avec `messagerie(broker)` dans son lifespan.

## Structure

```text
services/echo/
  openapi.yaml           contrat écrit d'abord, vérifié par tests/contract
  Dockerfile             multi-étapes (uv puis image finale non root), construit depuis la racine
  alembic.ini, alembic/  migrations (lancées par le conteneur echo-migrations) ; 0002 crée les
                         tables de messagerie (migration type à reprendre)
  src/echo/
    config.py            Pydantic Settings : DATABASE_URL, INSTANCE, PORT, CONSUL_ACTIF, JWT_*, JWKS_URL
    principal.py         creer_app() : journaux, erreurs, corrélation, base, Consul, routes
    api/                 routes, schémas, dépendances
    domaine/             règles, erreurs métier (ErreurMetier) et interface du dépôt, sans SQLAlchemy
    infra/               SQLAlchemy 2 async, implémentation du dépôt
  tests/
    unit/                routes avec un dépôt en mémoire, sans Docker
    integration/         vraie base PostgreSQL (Testcontainers) et vraies migrations
    contract/            schéma généré contre openapi.yaml (pytest -m contract)
```

## Ajouter un service sur ce modèle

Exemples déjà construits ainsi : `services/catalogue`, `billets`, `commandes`, `paiements`,
`notifications` (squelettes de BIL-001).

1. Copier la structure et renommer le paquet (`pyproject.toml`, `module-name`).
2. Ajouter sa base dans `infra/postgres/init/01-bases.sh` et son mot de passe dans `.env.example`.
3. Ajouter `services/<nom>` aux membres du workspace (`[tool.uv.workspace] members`), puis
   `services/<nom>/src` à `[tool.mypy] files` et le module à `known-first-party` ; `uv sync`
   met `uv.lock` à jour.
4. Ajouter `COPY services/<nom>/pyproject.toml services/<nom>/` dans **tous** les Dockerfiles
   du workspace (chaque service, `infra/verificateur/Dockerfile`), avant le premier
   `uv sync --locked` : uv lit le `pyproject.toml` de chaque membre pour valider `uv.lock`, une
   image sans lui ne se construit plus.
5. Dans `principal.py`, annoncer à Consul `tags_traefik(NOM_SERVICE, *RESSOURCES)` et
   `tags_sante_traefik(NOM_SERVICE, RESSOURCES[0])` (santé exposée par Traefik, jeton requis).
6. Créer la migration Alembic initiale (`alembic.ini`, `alembic/env.py`,
   `alembic/versions/0001_initiale.py`, vide si le service n'a pas encore de table).
7. Ajouter le service (nom et Dockerfile) à la matrice du job `images` de la CI.
8. Déclarer dans le compose `<nom>-migrations` puis ses instances `<nom>-1`, `<nom>-2`…, sans
   port publié ; `RABBITMQ_URL` seulement si le service publie ou consomme des événements.
9. Dans ce cas seulement, reprendre la migration `0002_creer_tables_messagerie.py` et
   `METADONNEES_MESSAGERIE` dans `alembic/env.py`.
