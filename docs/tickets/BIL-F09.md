# BIL-F09 : Keycloak (realm billetterie, rôles et clients)

- **Branche** : `feat/bil-f09-keycloak`
- **Dépend de** : BIL-F05

## Objectif

Ajouter Keycloak avec un realm `billetterie` versionné, ses rôles et ses clients OAuth 2.0 de base.

## Étapes

- [x] 1. Conteneur Keycloak (mode dev en local) avec sa propre base PostgreSQL, exposé par
  Traefik sur `/auth`, sur le même domaine que le front et l'API (`http://localhost`)
- [x] 2. Realm `billetterie` dans `infra/keycloak/realm-billetterie.json`, importé au démarrage
- [x] 3. Rôles `customer`, `partner`, `admin`
- [x] 4. Client `frontend` public, Authorization Code + PKCE ; redirections et Web Origins limitées
  à `http://localhost`
- [x] 5. Client `services` confidentiel, Client Credentials
- [x] 6. Jetons d'accès de 5 minutes ; utilisateurs de test synthétiques (un par rôle)

## Critères d'acceptance

- [x] CA1 : après `make reset` (équivalent de `docker compose down -v`) puis `make up`, le realm
  est recréé à l'identique (configuration comparée avant et après)
- [x] CA2 : le client `services` obtient un jeton par Client Credentials
- [x] CA3 : le jeton contient les rôles attendus (chaque utilisateur de test, connecté par PKCE,
  reçoit son seul rôle métier)

## Contraintes

- Secrets de clients uniquement dans `.env`, jamais dans l'export JSON : le realm ne contient
  que des variables `${...}`, vérifié par `tests/unit/test_realm_keycloak.py`.

## Décisions

- Gateway déplacée du port 8000 au port 80 (`http://localhost`) ; base `keycloak` dans le serveur
  PostgreSQL existant (choix validés par le développeur).
- Route `/auth` déclarée dans Consul par `infra/consul/keycloak.json`, avec ses tags Traefik.
