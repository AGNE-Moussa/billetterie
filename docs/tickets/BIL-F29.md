# BIL-F29 : Environnement de démo : VPS unique, domaine et Neon

- **Branche** : `feat/bil-f29-env-demo`
- **Dépend de** : BIL-F25, BIL-F28
- **Service** : infra

## Objectif

Préparer le VPS de démo et y déployer toute la plateforme (infrastructure, service echo et front)
derrière Traefik sur un domaine perso, pour que le déploiement final ne soit qu'une formalité.

## Étapes

- [ ] 1. VPS : Oracle Always Free ARM ; repli Contabo VPS 20 (environ 7 € par mois) si Oracle
  refuse la création ou devient instable. Docker, pare-feu (22, 80 et 443 seulement), connexion
  SSH par clé, utilisateur sans root, mises à jour de sécurité automatiques.
- [ ] 2. Nom de domaine perso (environ 10 € par an) : enregistrement A vers l'IP du VPS.
- [ ] 3. Projet Neon `billetterie`, une base par service ; URL de connexion dans les secrets
  GitHub, jamais dans le dépôt.
- [x] 4. `compose.prod.yaml` : sans PostgreSQL local (Neon via `DATABASE_URL`), Traefik avec TLS
  Let's Encrypt et redirection HTTP vers HTTPS, Keycloak en mode production sur `/auth`, front
  Nginx sur `/`, limites mémoire par conteneur (environ 3 Go au total).
- [x] 5. Workflow de déploiement déclenché manuellement : build multi-architecture des services
  et du front, push sur GHCR, migrations Alembic, `docker compose pull && up -d` sur le VPS par
  SSH (clé dans les secrets GitHub).
- [x] 6. Redirect URIs du client Keycloak `frontend` limitées au domaine de démo ; aucun CORS
  nécessaire, front et API ayant la même origine.

## Critères d'acceptance

- [ ] CA1 : `https://<domaine>/api/v1/echos/bonjour` répond en HTTPS
- [ ] CA2 : `https://<domaine>/` affiche le front, qui se connecte au Keycloak de démo et appelle
  l'API sans erreur CORS
- [ ] CA3 : aucun secret dans le dépôt ni dans les journaux de CI

## Contraintes

- Jamais de Neon dans les tests ; données de démo synthétiques et légères (0,5 Go par projet).

## Décisions (validation 1)

- Toutes les recommandations du plan retenues (`docs/test-plans/BIL-F29.md`, questions 1 à 19).
- Critères dérivés E1 à E5 ajoutés aux CA1 à CA3.
- Images `linux/amd64,linux/arm64`, taguées `sha-<commit>`, GHCR privé, retour arrière par une
  entrée `tag` du workflow.
- `DOMAINE` interpolé partout ; `.env.prod` écrit par le workflow sur le VPS (entrée standard de
  `ssh`, environment GitHub `demo`) ; modèle `.env.prod.example` vide, exception `.gitignore`.
- Prod : Traefik, Consul, vérificateur, Keycloak, RabbitMQ, echo (une instance),
  `echo-migrations`, frontend ; sans Prometheus, Grafana, Tempo, mailpit ni Redis ; ≤ 3072 Mio.
- `traefik.prod.yml` séparé, point d'entrée des tags Consul paramétré (`web` en local) ; ACME
  HTTP-01, volume nommé, staging d'abord ; seul Traefik publie 80 et 443.
- Neon : une base par service et une base `keycloak` ; migrations sur le VPS avant `up -d`.
- Realm unique paramétré par `KEYCLOAK_URL_FRONT` ; mots de passe de démo dans les secrets.
- Fichiers dans `/opt/billetterie` par `scp` ; gitleaks en CI ; `VPS_KNOWN_HOSTS` ; déploiement
  limité à `main` ; `CORS_ORIGINS=https://<domaine>`.
- Smoke sans jeton (401 problem+json) ; appel avec jeton en recette manuelle.

## Décisions (squelette)

- Liste blanche d'`implementer` élargie à `compose.prod.yaml` et
  `.github/workflows/deploiement.yml` (accord du développeur).
- `.env.prod.example` et l'exception `!.env.prod.example` du `.gitignore` posés à la main par le
  développeur (fichiers protégés).
- Variable du point d'entrée : `TRAEFIK_POINT_ENTREE` (`commun.registre.VARIABLE_POINT_ENTREE`),
  `web` par défaut.
- Définitions Consul de prod dans `infra/consul/prod/` (`entrypoints=websecure`), montées par
  `compose.prod.yaml` ; `infra/consul/` local inchangé.
- Tests : PyYAML lit la clé `on:` d'un workflow comme `True` (YAML 1.1).

## Décisions (tests)

- Smoke (`tests/smoke/test_demo.py`, `DEMO_URL`, sans jeton) posés par la skill `/smoke-tests` :
  `tests/smoke/` est interdit à `integration-test-writer`.
- Scan de secrets : job de `ci.yml` avec l'image `zricethezav/gitleaks` à version fixée, tout
  l'historique (`fetch-depth: 0`), `--redact`, sans fichier d'exceptions ; prouvé par la CI de
  la PR.
- Secrets SSH du workflow : `VPS_HOTE`, `VPS_UTILISATEUR`, `VPS_CLE_SSH`, `VPS_KNOWN_HOSTS`.
- Gardés verts (garde-fous) : tableau de bord coupé, front sans URL absolue, déclenchement
  manuel seul, CI sans secret, configuration de prod valide.
- Rouge mesuré : unitaires 19 failed, 15 passed ; intégration 19 failed, 1 passed (assertions).

## Décisions (implémentation)

- Fixture `secrets_realm` complétée par `KEYCLOAK_URL_FRONT=http://localhost` (aller-retour au
  marqueur `tests`) : le realm paramétré empêchait Keycloak de démarrer dans 12 tests existants.
- Sur le VPS : `pull`, puis migrations (`run --rm echo-migrations`), puis `up -d --wait`.
- `CORS_ORIGINS`, `KEYCLOAK_URL_FRONT`, `KC_HOSTNAME`, `JWT_EMETTEUR` dérivés de `DOMAINE` ;
  `TRAEFIK_POINT_ENTREE=websecure` écrit dans `compose.prod.yaml`.
- Traefik de prod lancé par `infra/traefik/demarrer-prod.sh`, qui substitue `DOMAINE`,
  `ACME_EMAIL`, `ACME_CA_SERVER` dans la configuration statique.
- Validés : propriétaire GHCR en dur (`ghcr.io/agne-moussa/billetterie-<image>`), secrets
  `GHCR_UTILISATEUR` / `GHCR_TOKEN` (`read:packages`), `ACME_EMAIL` en secret,
  `ACME_CA_SERVER` obligatoire (`vars`, staging d'abord), `restart: unless-stopped`, journaux
  `json-file` 3 × 10 Mo, RabbitMQ sans management, gitleaks `v8.28.0`.

## Décisions (validation 2)

- Review `docs/reviews/BIL-F29.md` : 0 bloquant, 3 à corriger, 8 suggestions.
- Point 1 : `.env.prod.example` aligné sur les 18 variables par le développeur (à la main).
- Point 2 : entrée `tag` du workflow validée (`^sha-[0-9a-f]{7,40}$`) avant tout usage.
- Point 3 : valeurs de `.env.prod` écrites entre guillemets simples (un `$` n'est pas interprété).
- Point 5 : `chmod 600` explicite sur `.env.prod` ; point 6 : `if` dupliqué retiré ; point 9 :
  `DOMAINE` validé dans `demarrer-prod.sh` ; point 10 : commentaire d'en-tête corrigé.
- Point 8 : `/auth/admin` exclu du routeur Keycloak de prod (administration par tunnel SSH).
- Limites acceptées : nom d'utilisateur GHCR visible dans la commande `ssh` et jeton GHCR gardé
  dans `~/.docker/config.json` du VPS (point 4) ; le retour arrière ne ramène que les images, et
  `scp -r` ne supprime pas les fichiers retirés du dépôt (point 7).
- Point 11 : l'exception `!.env.prod.example` fonctionne (vérifiée par `git check-ignore`).
- Tests d'abord (marqueur `tests`), puis implémentation.
- Limite : les valeurs de `.env.prod` étant entre guillemets simples, aucun secret ne doit
  contenir d'apostrophe (`'`).
- `test_demarrer_prod.py` exécute le script avec un `sh` POSIX (fixture `path_posix`, PATH du
  même environnement) ; un environnement cassé (code 127, « not found ») échoue au lieu de passer.
