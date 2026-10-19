# ADR-001 : pile technique

- **Statut** : acceptée
- **Date** : 2026-10-19

## Contexte

La billetterie est une plateforme en microservices : Catalogue, Billets, Commandes, Paiements,
Notifications, puis File d'attente en V2. Elle doit répondre à un défi propre : vendre un stock
limité sous une charge extrême, sans jamais vendre une place deux fois, et rester utilisable
pendant le pic d'ouverture des ventes.

L'architecture a donc besoin de :

- un registre de services et un point d'entrée unique qui répartit les appels entre les seules
  instances saines (Billets et Commandes tournent en deux instances) ;
- un serveur d'autorisation OAuth 2.0 / OIDC pour les clients du front, les revendeurs
  partenaires et les appels entre services ;
- une file de messages pour les événements asynchrones `ticketing.*` ;
- de la résilience sur les appels synchrones : timeout, nouvelles tentatives, disjoncteur.

Une grande partie du code est produite par des agents IA puis relue par le développeur. La
fiabilité de cette relecture dépend directement de la maîtrise du langage utilisé.

## Décision

| Besoin | Choix |
|---|---|
| Services métier | **Python 3.12 / FastAPI**, Pydantic v2, SQLAlchemy 2, Alembic |
| Registre de services | **Consul** (enregistrement, health checks, découverte) |
| API Gateway et load balancing | **Traefik v3**, fournisseur Consul Catalog |
| Serveur d'autorisation | **Keycloak**, realm `billetterie` |
| Validation des jetons | ForwardAuth de Traefik vers un vérificateur FastAPI |
| File de messages | **RabbitMQ** (exchange topic `ticketing`), via **FastStream** |

Toute nouvelle technologie passe par un nouvel ADR dans `docs/adr/`.

## Alternatives écartées

### Spring Cloud (Java)

Spring Cloud fournit d'origine la plupart des briques nécessaires : registre (Eureka), gateway
(Spring Cloud Gateway), résilience (Resilience4j).

Écarté : la relecture du code produit par les agents IA est plus fiable dans le langage maîtrisé,
Python. Gagner du temps sur l'infrastructure ne compense pas le risque de laisser passer une
erreur à la relecture, en particulier sur la règle « une place n'est jamais vendue deux fois ».

## Conséquences

### Positives

- Un seul langage pour tous les services : relecture plus fiable, outillage unique (uv, ruff,
  mypy strict, pytest).
- Consul et Traefik sont indépendants du langage : les services ne contiennent aucun code de
  découverte ni de routage.
- Keycloak couvre les trois flux OAuth 2.0 du projet (Authorization Code + PKCE, Client
  Credentials pour les revendeurs et entre services) sans code d'authentification maison.

### Négatives

- FastAPI n'apporte pas l'équivalent de Spring Cloud : la résilience, l'outbox et la propagation
  de l'identifiant de corrélation doivent être écrites une fois dans `libs/commun`
  (tickets BIL-F11 à BIL-F14).
- Le disjoncteur est maison (client HTTP commun : httpx, tenacity, disjoncteur maison) : il doit
  être testé avec soin.
- Plus de composants d'infrastructure à faire tourner en local (Consul, Traefik, Keycloak,
  RabbitMQ) : un Docker Compose complet est nécessaire (BIL-F05).
