# Review : BIL-F29, Environnement de démo : VPS unique, domaine et Neon

- Diff relu : `git diff main` (branche sans commit propre, tout le travail est non commité) et
  fichiers non suivis de `git status --short` : 26 fichiers (10 modifiés, 16 nouveaux, dont le
  ticket et le plan)
- Verdict : 0 bloquant, 3 à corriger, 8 suggestions

Mesures reprises de l'orchestrateur (non relancées ici, revue en lecture seule) : `make lint`,
`make typecheck`, `make test-unit` 420 passed, `make test-integration` 56 passed,
`docker compose -f compose.yaml config` OK, smoke 10 skipped sans `DEMO_URL`. Non vérifiables
ici : job gitleaks (prouvé par la CI de la PR) et déploiement réel (recette R1 à R6).

## Points

| # | Classement | Fichier:ligne | Constat | Attendu |
|---|---|---|---|---|
| 1 | à corriger | `.env.prod.example:3-13` | Le modèle ne correspond pas aux variables lues par `compose.prod.yaml` et écrites par le workflow (`deploiement.yml:152-170`), qui sont les mêmes 18 variables. **Manquent 10 variables** : `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`, `KEYCLOAK_REALM`, `KEYCLOAK_SERVICES_SECRET`, `KEYCLOAK_MDP_CLIENT`, `KEYCLOAK_MDP_PARTENAIRE`, `KEYCLOAK_MDP_ADMIN`, `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS`, `ROUTES_PUBLIQUES`. **3 variables sont en trop** : `KEYCLOAK_URL_FRONT`, `CORS_ORIGINS` et `TRAEFIK_POINT_ENTREE`. Elles sont dérivées de `DOMAINE` ou écrites en dur dans `compose.prod.yaml` (lignes 34, 129, 178), donc jamais lues dans `.env.prod`. | Le modèle (fichier protégé, à mettre à jour par le développeur) liste exactement les 18 variables : `DOMAINE`, `IMAGE_TAG`, `ACME_EMAIL`, `ACME_CA_SERVER`, `ECHO_DATABASE_URL`, `KEYCLOAK_DB_URL`, `KEYCLOAK_DB_USERNAME`, `KEYCLOAK_DB_PASSWORD`, `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`, `KEYCLOAK_REALM`, `KEYCLOAK_SERVICES_SECRET`, `KEYCLOAK_MDP_CLIENT`, `KEYCLOAK_MDP_PARTENAIRE`, `KEYCLOAK_MDP_ADMIN`, `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS`, `ROUTES_PUBLIQUES`, toutes avec une valeur vide. Les 3 variables dérivées sont retirées. On peut les citer dans un commentaire « dérivées de DOMAINE ». Le test `test_le_modele_d_environnement_de_prod_n_a_que_des_valeurs_vides` reste vert. |
| 2 | à corriger | `.github/workflows/deploiement.yml:86-93` | L'entrée `tag` est recopiée telle quelle dans `$GITHUB_OUTPUT`, puis dans `.env.prod` (ligne 154). L'API `workflow_dispatch` accepte un retour à la ligne : on peut alors ajouter une sortie d'étape, ou une ligne `NOM=valeur` dans `.env.prod` qui écrase une variable écrite plus haut. Seules les personnes ayant le droit d'écriture peuvent lancer le workflow, le risque est donc faible. Mais c'est une injection possible dans un fichier qui porte des secrets. | Valider le tag avant de l'utiliser, par exemple `case`/`grep -Eq '^sha-[0-9a-f]{7,40}$'`, et faire échouer l'étape sinon. |
| 3 | à corriger | `.github/workflows/deploiement.yml:152-171` | Les valeurs sont écrites dans `.env.prod` sans guillemets (`NOM=%s`). Compose interpole les valeurs sans guillemets d'un fichier d'environnement : un mot de passe qui contient `$` (Keycloak, RabbitMQ, Neon) sera corrompu sans aucune erreur. Exemple : `ab$cd` devient `ab`. | Écrire les valeurs entre guillemets simples (Compose les lit alors littéralement), ou documenter dans `.env.prod.example` et le workflow que les secrets ne contiennent ni `$` ni `'`. |
| 4 | suggestion | `.github/workflows/deploiement.yml:173` | `$GHCR_UTILISATEUR` est développé sur le runner, puis passé dans la chaîne de commande distante de `ssh`. Il est donc visible dans les arguments de processus du VPS, et un `"` ou un `;` dans la valeur casserait la commande. Ce n'est pas un vrai secret, et GitHub masque la valeur dans les journaux. | Passer aussi le nom d'utilisateur par l'entrée standard, ou le mettre en `vars` en le validant. Noter aussi que `docker login` laisse le jeton `read:packages` en base64 dans `~/.docker/config.json` de l'utilisateur de déploiement. C'est acceptable pour un jeton en lecture seule, mais à indiquer dans la recette. |
| 5 | suggestion | `.github/workflows/deploiement.yml:171` | `umask 077` ne s'applique qu'à la création du fichier. Si `.env.prod` existe déjà avec d'autres droits (posé à la main, par exemple), `cat >` garde ces droits. | `umask 077 && cat > .env.prod && chmod 600 .env.prod`, ou `install -m 600 /dev/stdin .env.prod`. |
| 6 | suggestion | `.github/workflows/deploiement.yml:56` | `if: inputs.tag == ''` sur l'étape `build-push-action` répète la condition du job (ligne 27). | Garder la condition du job seule. Le test `test_le_deploiement_accepte_un_tag_pour_revenir_en_arriere` accepte la condition sur le job ou sur l'étape. |
| 7 | suggestion | `.github/workflows/deploiement.yml:120-127` | Le retour arrière (entrée `tag`) redéploie les anciennes images, mais avec le `compose.prod.yaml`, le realm et les définitions Consul de la tête de `main`. Ces fichiers peuvent ne plus correspondre aux anciennes images. De plus, `scp -r` ne supprime pas sur le VPS un fichier retiré du dépôt : une ancienne définition Consul resterait montée. | Écrire cette limite dans le commentaire d'en-tête du workflow (le retour arrière ne concerne que les images). Pour les fichiers obsolètes : vider `infra/consul/prod` avant la copie, ou utiliser `rsync --delete`. |
| 8 | suggestion | `compose.prod.yaml:106-123` | La console d'administration (`/auth/admin`) est publique sur le domaine de démo, via la chaîne `public@file`. Elle n'est protégée que par le compte admin de bootstrap. Le ticket ne demande pas de la couper : c'est une décision à remonter, pas à trancher ici. | Question au développeur : restreindre `/auth/admin` (routeur Traefik dédié, ou liste d'IP autorisées), ou noter le risque dans la recette. |
| 9 | suggestion | `infra/traefik/demarrer-prod.sh:9-22` | La substitution de `DOMAINE`, `ACME_EMAIL` et `ACME_CA_SERVER` est bien échappée pour `sed`, mais aucune valeur n'est validée. Un `"` dans `DOMAINE` casserait le YAML entre guillemets. Aucun test ne prouve non plus que la substitution a eu lieu : la redirection et le routage testés reposent sur l'en-tête `Host`, et l'autorité ACME est injoignable dans tous les cas. | Valider le format de `DOMAINE` dans le script (`case` sur `*[!a-z0-9.-]*`). En recette, au premier déploiement, vérifier `/etc/traefik/traefik.yml` dans le conteneur (`docker compose exec traefik cat ...`) et lire les journaux ACME en staging. |
| 10 | suggestion | `compose.prod.yaml:4-7` | Le commentaire d'en-tête donne l'ordre migrations, `pull`, `up`. Le workflow et la décision d'implémentation donnent `pull`, migrations, `up -d --wait`, avec `COMPOSE_ENV_FILES` au lieu de `--env-file`. | Aligner le commentaire sur l'ordre réel : `pull`, puis `run --rm echo-migrations`, puis `up -d --wait`. |
| 11 | suggestion | `.gitignore:390-393` | Deux lignes vides avant `!.env.prod.example` et pas de fin de ligne finale. L'exception est isolée en fin de fichier, sans commentaire, loin de `.env.*` (ligne 295). | Placer l'exception à côté de `!.env.example`, avec un commentaire « BIL-F29 », et ajouter la fin de ligne (fichier protégé : à faire par le développeur). |

## Vérifications faites sans écart

- **Ticket et contrat** :
  - Étapes 4 à 6 traitées.
  - Composition retenue : 8 services, ni PostgreSQL, ni Redis, ni observabilité, ni mailpit.
  - Limites mémoire : 2368 Mio au total. Heap Keycloak `-Xmx640m` pour une limite de 1024 Mio.
  - Images GHCR `:${IMAGE_TAG}`, aucune section `build`.
  - Toutes les variables sensibles en `${VAR:?}`.
  - Keycloak : `start --import-realm`, `KC_HTTP_ENABLED`, `KC_PROXY_HEADERS=xforwarded`, `KC_HOSTNAME=https://${DOMAINE}/auth`.
  - `JWT_EMETTEUR` aligné sur le domaine. Echo sans `OTEL_EXPORTER_OTLP_ENDPOINT` : `commun/observabilite.py:84` n'exporte rien dans ce cas.
  - Dépendances et healthchecks cohérents : `echo` attend migrations, Consul et RabbitMQ ; Traefik attend Consul.
- **Traefik** :
  - Redirection permanente `web` vers `websecure`, ACME HTTP-01 sur `web`, `caServer` paramétré (staging d'abord), stockage `/acme/acme.json` sur le volume `traefik-acme`.
  - Domaine du certificat donné sur `websecure`. Tableau de bord coupé. Point d'entrée `traefik` (8080) non publié.
  - Le script lance Traefik par `exec`. `traefik healthcheck` lit le fichier généré à l'emplacement par défaut.
  - Seul Traefik publie 80 et 443 : rien ne contourne UFW.
- **Sécurité, CA3** :
  - Aucun secret ni valeur réaliste dans les fichiers relus (domaine `demo.exemple.test`, valeurs `secrets.token_urlsafe`).
  - Aucun `${{ secrets.* }}` dans un `run:`, tous passent par `env:`. Ni `set -x`, ni `echo` de secret, ni `docker compose config` dans le workflow.
  - `.env.prod` transmis par l'entrée standard de `ssh` sous `umask 077`. Jeton GHCR passé par `--password-stdin`.
  - `StrictHostKeyChecking=yes` avec `VPS_KNOWN_HOSTS`. Clé privée en 600.
  - `permissions: contents: read` au niveau du workflow, `packages: write` sur le seul job `images`.
  - Les deux jobs sont limités à `refs/heads/main`. `environment: demo`. `concurrency` sans annulation.
  - Gitleaks à version fixée (`v8.28.0`), avec `fetch-depth: 0`, `--redact` et sans fichier d'exceptions.
- **Non-régression locale** :
  - `tags_traefik` donne `web` par défaut (paramètre, puis variable, puis défaut).
  - Realm paramétré par `${KEYCLOAK_URL_FRONT}` (`redirectUris`, `webOrigins`, `post.logout.redirect.uris`).
  - `compose.yaml` passe `${KEYCLOAK_URL_FRONT:-http://localhost}`. `.env.example` documente la variable avec une valeur vide.
  - `infra/consul/` local inchangé. `make up` utilise déjà `--wait` avec `echo-migrations` (`Makefile:30`).
- **Tests** :
  - Les cas du plan E1 à E6, CA1, CA2 et CA3 sont tous présents, avec les noms du plan.
  - L'ordre `pull`, migrations, `up` suit la décision d'implémentation : le test exige seulement les migrations avant `up -d`.
  - Fixture `secrets_realm` : une ligne ajoutée (`KEYCLOAK_URL_FRONT`), conforme aux décisions d'implémentation.
  - `test_roles_et_clients_attendus` : seule l'assertion prévue en Q14 change.
  - Smoke `tests/smoke/test_demo.py` : requêtes sans jeton, ignoré sans `DEMO_URL`.
  - Aucun test affaibli constaté. La branche n'a aucun commit : on ne peut pas prouver par `git` l'absence de modification des tests depuis l'étape `tests`, mais les seuls changements visibles sont ceux que les décisions documentent.

## Grille

| Axe | Résultat |
|---|---|
| Ticket et contrat | conforme (étapes 4 à 6, E1 à E6) ; CA1 et CA2 relèvent de la recette sur le domaine réel ; point 1 (modèle d'environnement) |
| Rules | conforme (sécurité, tests, git) ; points 10 et 11 (lisibilité de fichiers de configuration) |
| Sécurité | conforme sur les exigences du ticket ; points 2, 3, 4, 5, 8, 9 |
| Résilience | non concerné (aucun appel entre services ni événement ajouté) ; point 7 (retour arrière) |
| Tests | conforme au plan validé ; seul changement de fixture, celui documenté ; aucun test affaibli |
| Lisibilité | points 6 et 10 |
