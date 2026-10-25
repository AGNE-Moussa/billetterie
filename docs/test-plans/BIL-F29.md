# Plan de test : BIL-F29, Environnement de démo : VPS unique, domaine et Neon

- Ticket : `docs/tickets/BIL-F29.md` ; contrat : `services/echo/openapi.yaml` (opération
  `lireEcho`, sécurisée : seulement pour l'attendu de CA1)
- Niveaux : unitaire, intégration, smoke (contre le domaine de démo, hors CI), recette manuelle

Périmètre : ticket d'infrastructure. Une partie du travail se fait à la main par le développeur,
hors du dépôt, et aucun agent ne peut la faire ni la tester : création du VPS, achat du domaine
et enregistrement A, projet Neon et ses bases, secrets GitHub, durcissement du VPS (pare-feu 22,
80 et 443, SSH par clé, utilisateur sans root, mises à jour automatiques). Le plan a donc deux
parties :

- **Partie A, automatisée dans le dépôt, sans Neon ni VPS** : les fichiers livrés
  (`compose.prod.yaml`, configuration Traefik de prod, realm Keycloak, workflow de déploiement)
  sont vérifiés en `unitaire` (lecture YAML/JSON par PyYAML, déjà en dépendance de dev) et en
  `intégration` (`docker compose config` sur un fichier d'environnement synthétique, Traefik et
  Keycloak en conteneur avec la configuration de prod, base PostgreSQL Testcontainers). Ces cas
  vérifient les étapes 4 à 6, reprises en critères dérivés E1 à E5 (voir Q1), et la partie
  « dépôt » de CA3.
- **Partie B, recette sur le domaine réel** : CA1, CA2 et la partie « journaux de CI » de CA3.
  Une checklist de recette manuelle, plus quelques smoke tests (`tests/smoke/`, marqueur
  `smoke`, jamais lancés par la CI) qui n'envoient que des requêtes sans jeton (voir Q9).

Contrainte du ticket : **jamais de Neon dans les tests**. Aucun cas de la partie A ne lit un
secret GitHub ni une URL Neon ; les bases viennent de Testcontainers. Le ticket ne touche ni
Billets ni Commandes : aucun cas de concurrence obligatoire.

Données synthétiques communes :

- Domaine de test : `demo.exemple.test` (jamais le vrai domaine dans un test).
- Fichier d'environnement de test écrit dans `tmp_path`, valeurs générées par
  `secrets.token_urlsafe` : `DOMAINE=demo.exemple.test`,
  `DATABASE_URL=postgresql+asyncpg://echo:<généré>@base.exemple.test:5432/echo`,
  `ACME_EMAIL=acme.test@exemple.test`, mots de passe Keycloak générés, `IMAGE_TAG=sha-0000000`
  (noms exacts : dépend de Q3, Q10, Q11, Q15).
- Fixture d'intégration `config_prod` (portée module) : sortie JSON de
  `docker compose -f compose.prod.yaml --env-file <fichier de test> config --format json`, qui
  résout ancres, interpolation et normalise les limites mémoire en octets.

Existant à garder vert : `tests/unit/test_realm_keycloak.py` (son assertion
`redirectUris == ["http://localhost/*"]` change si le realm est paramétré, voir Q14),
`tests/integration/test_gateway.py`, `tests/integration/test_keycloak.py`, le job `images` de
`.github/workflows/ci.yml` (déjà multi-architecture, sans publication) et `make up` en local
(`compose.yaml` inchangé dans son comportement).

## Questions

**Réponses du développeur (validation 1, 2026-10-25)** : toutes les recommandations ci-dessous
sont retenues telles quelles (questions 1 à 19). Le plan est validé.

1. Les critères dérivés E1 à E5 (tirés des étapes 4, 5 et 6) sont-ils validés comme critères
   testables du ticket, à côté de CA1 à CA3 ? Recommandation : oui, comme pour BIL-F25 ; sans
   eux, la partie A n'aurait aucun critère de rattachement.
2. Fournisseur du VPS et architecture : Oracle Always Free ARM (arm64) ou repli Contabo VPS 20
   (amd64) ; c'est le développeur qui crée le VPS, à la main. Recommandation : publier toujours
   `linux/amd64,linux/arm64` (le repli ne demande alors aucun changement du workflow) ; les tests
   exigent les deux plateformes.
3. Nom de domaine, registrar et injection du domaine : variable `DOMAINE` dans un `.env.prod`
   posé sur le VPS (jamais commité) et `vars.DOMAINE` (variable GitHub, non secrète) pour le
   workflow ? Attention : `.gitignore` ignore `.env.*` sauf `.env.example`, un modèle
   `.env.prod.example` serait donc ignoré sans exception ajoutée. Recommandation : `DOMAINE`
   lu partout par interpolation `${DOMAINE:?...}`, modèle `.env.prod.example` aux valeurs vides
   avec une exception `!.env.prod.example` dans `.gitignore`.
4. Composition de la prod dans environ 3 Go : quels conteneurs ? Traefik route par le
   catalogue Consul (`providers.consulCatalog`) et trace vers Tempo ; echo publie son outbox sur
   RabbitMQ et exporte ses traces vers Tempo ; le vérificateur est dans la chaîne `standard`.
   Recommandation : garder Traefik, Consul, vérificateur, Keycloak, RabbitMQ, echo (une seule
   instance), `echo-migrations` et frontend ; retirer Prometheus, Grafana, Tempo, mailpit et
   Redis (aucun service déployé ne l'utilise encore) ; sans Tempo, retirer `tracing` de la
   configuration statique de prod et vider `OTEL_EXPORTER_OTLP_ENDPOINT`, à condition qu'echo
   démarre sans exportateur (à vérifier).
5. Limites mémoire : syntaxe (`deploy.resources.limits.memory` ou `mem_limit`), répartition,
   tolérance de « environ 3 Go », et un conteneur ponctuel (`echo-migrations`) compte-t-il dans
   le total ? Recommandation : `deploy.resources.limits.memory` sur chaque service, total
   ≤ 3072 Mio, conteneur ponctuel compté ; par exemple Keycloak 1024 Mio (avec
   `JAVA_OPTS_KC_HEAP` bornée), RabbitMQ 384, echo 256, `echo-migrations` 256, Consul 128,
   Traefik 128, vérificateur 128, frontend 64.
6. Où configurer TLS et la redirection, et comment adapter les tags Consul ? Les routes
   viennent des tags (`infra/consul/*.json`, `commun.registre.tags_traefik`, qui écrit en dur
   `entrypoints=web`). Recommandation : configuration statique de prod séparée
   (`infra/traefik/traefik.prod.yml`), redirection permanente `web` vers `websecure` au niveau
   du point d'entrée, `websecure.http.tls.certResolver=letsencrypt`, et point d'entrée des tags
   paramétré (variable lue par `tags_traefik`, `web` par défaut en local) ; ne pas passer au
   fournisseur Docker (labels), qui changerait le modèle de routage.
7. Certificats ACME : type de challenge, adresse e-mail, stockage, autorité de test ?
   Recommandation : challenge HTTP-01 sur `web`, `ACME_EMAIL` dans `.env.prod`, `acme.json`
   sur un volume nommé (`traefik-acme`), autorité de staging de Let's Encrypt au premier
   déploiement (variable `ACME_CA_SERVER`) pour ne pas épuiser les quotas.
8. Ports publiés et tableau de bord : Docker contourne le pare-feu de l'hôte (règles iptables
   ajoutées avant celles d'UFW), le pare-feu 22/80/443 ne protège donc pas un port publié par
   Compose. Recommandation : en prod, seul Traefik publie des ports (80 et 443) ; tableau de
   bord coupé (`api.insecure` absent ou `false`), point d'entrée `traefik` (8080) non publié.
9. CA1 « répond en HTTPS » : quel statut attendu ? `lireEcho` est protégé : sans jeton, la
   gateway répond 401 ; avec jeton, 200 seulement si l'echo `bonjour` existe (sinon 404). Et un
   smoke test contre la démo touche-t-il Neon, ce que le ticket interdit aux tests ?
   Recommandation : le smoke n'envoie que des requêtes sans jeton (TLS valide, 401
   `application/problem+json` produit par le vérificateur, avant tout accès à la base) ; l'appel
   avec jeton et l'echo `bonjour` créé une fois comme donnée de démo restent dans la recette
   manuelle.
10. Base de Keycloak : une base `keycloak` dans le projet Neon aussi ? Elle demande une URL JDBC
    (`KC_DB_URL`, `sslmode=require`) distincte du format asyncpg. Recommandation : oui, base
    Neon `keycloak`, secrets `KEYCLOAK_DB_URL`, `KEYCLOAK_DB_USERNAME`, `KEYCLOAK_DB_PASSWORD` ;
    surveiller le quota de 0,5 Go.
11. Un secret `DATABASE_URL` unique ou un par service ? Le ticket dit « une base par service ».
    Recommandation : un secret par service (`ECHO_DATABASE_URL`, puis un par nouveau service),
    passé au conteneur sous le nom `DATABASE_URL` ; noter qu'asyncpg attend `ssl=require` et
    non `sslmode=require`.
12. Migrations Alembic : depuis le runner GitHub vers Neon, ou sur le VPS par
    `docker compose run --rm echo-migrations` lancé par SSH ? Recommandation : sur le VPS, avant
    `up -d` (même image que le service, pas d'accès réseau du runner à Neon, une seule copie des
    URL de base, sur le VPS) ; à confirmer, l'étape 5 citant les migrations parmi les étapes du
    workflow sans en fixer le lieu.
13. Comment les secrets arrivent-ils sur le VPS : `.env.prod` posé à la main par le développeur
    (droits 600), ou écrit par le workflow depuis les secrets GitHub à chaque déploiement ?
    Recommandation : écrit par le workflow, transmis par l'entrée standard de `ssh` (jamais en
    argument de commande ni par `echo`), depuis un `environment` GitHub `demo` qui porte les
    secrets.
14. Realm de démo et utilisateurs de test : même `realm-billetterie.json` importé en prod, avec
    `client.test`, `partenaire.test`, `admin.test` ? Comment paramétrer les redirect URIs du
    client `frontend` (aujourd'hui `http://localhost/*` en dur, vérifié par
    `test_roles_et_clients_attendus`) ? Rappel : `--import-realm` n'écrase pas un realm existant,
    un changement de domaine demande une mise à jour manuelle. Recommandation : une variable
    `${KEYCLOAK_URL_FRONT}` dans le realm unique (`http://localhost` dans `.env`,
    `https://<domaine>` en prod) pour `redirectUris`, `webOrigins` et
    `post.logout.redirect.uris`, mots de passe des utilisateurs de démo dans les secrets.
15. Tags d'image, visibilité GHCR et retour arrière : quel tag déployé, paquets publics ou
    privés, et comment revenir à la version précédente ? Recommandation : tag `sha-<commit>`
    (plus `demo` pour la dernière version déployée), `IMAGE_TAG` interpolé dans
    `compose.prod.yaml`, paquets privés lus par le VPS avec un jeton `read:packages` en secret ;
    retour arrière en relançant le workflow avec une entrée `tag` égale à un ancien
    `sha-<commit>`.
16. Où vivent les fichiers sur le VPS et comment y arrivent-ils ? Recommandation : dossier
    `/opt/billetterie` appartenant à l'utilisateur de déploiement, copie par `scp` d'une liste
    fixe (`compose.prod.yaml`, configuration Traefik de prod, `infra/consul/`, realm), sans
    clone du dépôt sur le VPS.
17. Outil de scan de secrets du dépôt : aucun n'existe aujourd'hui (seul
    `test_realm_keycloak.py` vérifie le realm). Recommandation : gitleaks dans un job de
    `ci.yml`, sur tout l'historique (`fetch-depth: 0`), avec une liste d'exceptions limitée aux
    variables `${...}`.
18. Vérification de la clé d'hôte SSH du VPS et branche autorisée : recommandation, secret
    `VPS_KNOWN_HOSTS` avec `StrictHostKeyChecking=yes`, et job de déploiement limité à
    `refs/heads/main`.
19. Valeur de `CORS_ORIGINS` en prod : le middleware `cors` est dans les chaînes `standard` et
    `public` et lit cette variable (une valeur vide donne une origine vide autorisée). Le ticket
    dit qu'aucun CORS n'est nécessaire. Recommandation : `CORS_ORIGINS=https://<domaine>`, sans
    nouvelle chaîne de middlewares propre à la prod.

## E1 : `compose.prod.yaml` est valide et sans PostgreSQL local (étape 4)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_la_configuration_de_prod_est_valide_avec_un_environnement_synthetique` | intégration | `docker compose -f compose.prod.yaml --env-file <fichier de test> config --quiet` | code de sortie 0, aucune sortie d'erreur |
| `test_sans_database_url_la_configuration_de_prod_est_refusee` (dépend de Q11) | intégration | fichier de test sans la variable de l'URL de base d'echo | code de sortie non nul, message d'erreur qui nomme la variable manquante |
| `test_la_prod_ne_contient_aucun_service_postgres` | intégration | `config_prod` | aucun service dont l'image commence par `postgres` ; aucun volume `postgres-data` ; aucun `depends_on` vers `postgres` |
| `test_les_services_lisent_leur_base_dans_database_url` (dépend de Q11) | intégration | `config_prod` | `echo` et `echo-migrations` ont `DATABASE_URL` égale à la valeur du fichier de test ; aucune URL ne contient `@postgres:` |
| `test_la_prod_tire_les_images_de_ghcr_sans_construire` (dépend de Q15) | intégration | `config_prod` | chaque service maison (echo, vérificateur, frontend) a une image `ghcr.io/...:sha-0000000` et aucune section `build` |
| `test_la_prod_ne_garde_que_les_conteneurs_retenus` (dépend de Q4) | intégration | `config_prod` | ensemble des services égal à la liste retenue en Q4 ; ni `prometheus`, ni `grafana`, ni `mailpit` |
| `test_seul_traefik_publie_des_ports_et_seulement_80_et_443` (dépend de Q8) | intégration | `config_prod` | `traefik` publie exactement 80 et 443 ; aucun autre service n'a de `ports` |

## E2 : limites mémoire par conteneur, environ 3 Go au total (étape 4)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_chaque_conteneur_de_prod_a_une_limite_memoire` (dépend de Q5) | intégration | `config_prod` | chaque service a `deploy.resources.limits.memory` (en octets après normalisation) |
| `test_le_total_des_limites_memoire_tient_dans_le_budget_de_la_demo` (dépend de Q5) | intégration | `config_prod` | somme des limites ≤ 3072 Mio (3 221 225 472 octets), conteneurs ponctuels compris |
| `test_la_heap_de_keycloak_tient_dans_sa_limite_memoire` (dépend de Q5) | intégration | `config_prod`, service `keycloak` | la taille maximale de heap déclarée (`-Xmx` de `JAVA_OPTS_KC_HEAP`) est strictement inférieure à la limite du conteneur |

## E3 : Traefik en HTTPS avec Let's Encrypt et redirection HTTP vers HTTPS (étape 4, CA1)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_la_configuration_statique_de_prod_redirige_web_vers_websecure` (dépend de Q6) | unitaire | lecture de la configuration statique de prod | `entryPoints.web.http.redirections.entryPoint.to` = `websecure`, `scheme` = `https`, redirection permanente ; `websecure.address` = `:443` |
| `test_le_point_d_entree_https_utilise_le_resolveur_let_s_encrypt` (dépend de Q6, Q7) | unitaire | même fichier | `websecure.http.tls.certResolver` = nom d'un résolveur déclaré sous `certificatesResolvers` ; challenge `httpChallenge.entryPoint` = `web` |
| `test_les_certificats_acme_sont_stockes_sur_un_volume_persistant` (dépend de Q7) | intégration | `config_prod`, configuration statique de prod | `acme.storage` est sous un chemin monté par un volume nommé du service `traefik` |
| `test_l_adresse_acme_vient_de_l_environnement` (dépend de Q7) | unitaire | configuration statique de prod et `compose.prod.yaml` bruts | aucune adresse e-mail littérale ; la valeur vient d'une variable (`ACME_EMAIL`) |
| `test_le_tableau_de_bord_de_traefik_est_coupe_en_prod` (dépend de Q8) | unitaire | configuration statique de prod | `api.insecure` absent ou `false` |
| `test_les_tags_consul_visent_le_point_d_entree_https_en_prod` (dépend de Q6) | unitaire | `tags_traefik("echo", "echos")` avec la variable du point d'entrée à `websecure`, puis sans elle | `entrypoints=websecure` dans le premier cas ; `entrypoints=web` dans le second (local inchangé) |
| `test_les_definitions_consul_de_keycloak_et_du_front_suivent_le_point_d_entree_de_prod` (dépend de Q6) | intégration | `config_prod` et définitions Consul montées en prod | les routeurs `keycloak` et `frontend` sont sur `websecure` |
| `test_traefik_de_prod_redirige_http_vers_https_et_route_l_api` (dépend de Q6, Q7) | intégration | Traefik `v3.5.3` et Consul en conteneurs avec la configuration statique de prod, ACME pointé vers une autorité injoignable (certificat par défaut de Traefik), un service `whoami` inscrit sous `/api/v1/echos` en chaîne `public@file` | `GET http://.../api/v1/echos/bonjour` : 301 ou 308 vers `https://.../api/v1/echos/bonjour` ; même requête en HTTPS (vérification TLS coupée, `Host: demo.exemple.test`) : 200 venant de `whoami` |

## E4 : Keycloak en mode production sur `/auth`, front Nginx sur `/` (étape 4, CA2)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_keycloak_de_prod_demarre_en_mode_production` | intégration | `config_prod`, service `keycloak` | commande commençant par `start` et ne contenant pas `start-dev` |
| `test_keycloak_de_prod_publie_l_emetteur_https_du_domaine_sous_auth` (dépend de Q3) | intégration | `config_prod` | `KC_HTTP_RELATIVE_PATH` = `/auth` ; `KC_HOSTNAME` = `https://demo.exemple.test/auth` ; `KC_PROXY_HEADERS` = `xforwarded` |
| `test_le_verificateur_et_echo_attendent_l_emetteur_du_domaine` (dépend de Q3) | intégration | `config_prod` | `JWT_EMETTEUR` du vérificateur et d'echo = `https://demo.exemple.test/auth/realms/billetterie` (même origine que `KC_HOSTNAME`) |
| `test_keycloak_de_prod_lit_sa_base_dans_l_environnement` (dépend de Q10) | intégration | `config_prod` | `KC_DB_URL`, `KC_DB_USERNAME`, `KC_DB_PASSWORD` égaux aux valeurs du fichier de test ; aucune URL vers `postgres:5432` |
| `test_keycloak_en_mode_production_derriere_le_proxy_annonce_l_emetteur_https` (dépend de Q10, Q14) | intégration | Keycloak `26.4.1` lancé avec la commande et l'environnement de prod, base PostgreSQL 16 Testcontainers (jamais Neon), realm importé, `KC_HOSTNAME=https://demo.exemple.test/auth` | `GET /auth/realms/billetterie/.well-known/openid-configuration` (en-têtes `X-Forwarded-Proto: https`, `X-Forwarded-Host: demo.exemple.test`) : 200, `issuer` = `https://demo.exemple.test/auth/realms/billetterie` |
| `test_le_front_de_prod_est_route_sur_la_racine_hors_api_et_auth` | intégration | `config_prod` et définition Consul du front montée en prod | règle `PathPrefix(`/`) && !PathPrefix(`/api`) && !PathPrefix(`/auth`)`, priorité 1, chaîne `public@file` |
| `test_le_front_de_prod_n_embarque_aucune_url_d_api_ou_de_keycloak_absolue` | unitaire | workflow de déploiement et `compose.prod.yaml` bruts | aucun `VITE_API_URL` ni `VITE_KEYCLOAK_URL` passé au build du front : il garde `/api` et `/auth` relatifs (même origine, étape 6) |

## E5 : workflow de déploiement manuel, multi-architecture, GHCR, migrations, SSH (étape 5)

Fichier lu : le workflow de déploiement livré (par exemple `.github/workflows/deploiement.yml`),
en `unitaire`.

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_le_deploiement_ne_se_declenche_que_manuellement` | unitaire | clé `on` du workflow | exactement `workflow_dispatch` ; ni `push`, ni `pull_request`, ni `schedule`, ni `workflow_run` |
| `test_le_deploiement_ne_part_que_de_main` (dépend de Q18) | unitaire | jobs du workflow | le job de déploiement porte `if: github.ref == 'refs/heads/main'` |
| `test_le_deploiement_construit_echo_le_verificateur_et_le_front_pour_amd64_et_arm64` (dépend de Q2) | unitaire | étapes `docker/build-push-action` | une construction par image (echo, vérificateur, frontend), chacune avec `platforms: linux/amd64,linux/arm64` |
| `test_le_deploiement_publie_les_images_sur_ghcr` (dépend de Q15) | unitaire | même étapes, étape `docker/login-action` | `push: true` ; tags commençant par `ghcr.io/` et contenant `sha-` ; connexion à `ghcr.io` avec `secrets.GITHUB_TOKEN` ; `permissions.packages` = `write`, `contents` = `read` |
| `test_le_deploiement_applique_les_migrations_avant_de_relancer_les_services` (dépend de Q12) | unitaire | étapes du job de déploiement, dans l'ordre | une étape lance `alembic upgrade head` (ou `docker compose run --rm echo-migrations`) avant l'étape `docker compose pull` puis `up -d` |
| `test_le_deploiement_relance_la_plateforme_par_ssh_avec_compose_pull_et_up` (dépend de Q16) | unitaire | étape SSH | commande contenant `docker compose -f compose.prod.yaml pull` puis `up -d`, dans le dossier retenu en Q16 |
| `test_la_cle_ssh_et_l_hote_viennent_des_secrets` (dépend de Q18) | unitaire | étape SSH | clé privée, hôte, utilisateur et `known_hosts` lus dans `secrets.*` ; aucun `StrictHostKeyChecking=no` |
| `test_le_deploiement_accepte_un_tag_pour_revenir_en_arriere` (dépend de Q15) | unitaire | `on.workflow_dispatch.inputs` | une entrée `tag` facultative ; si fournie, aucune construction et ce tag est déployé |
| `test_les_jobs_de_test_de_la_ci_ne_recoivent_aucun_secret` | unitaire | `.github/workflows/ci.yml` | aucun `secrets.` dans les jobs `lint`, `types`, `unit`, `integration`, `contract`, `frontend`, `images` (jamais de Neon dans les tests) |

## E6 : redirect URIs du client `frontend` limitées au domaine de démo (étape 6, CA2)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_les_redirect_uris_du_client_frontend_sont_parametrees_par_le_domaine` (dépend de Q14) | unitaire | `infra/keycloak/realm-billetterie.json` | `redirectUris`, `webOrigins` et `post.logout.redirect.uris` du client `frontend` ne contiennent que la variable retenue en Q14 (forme `${...}`), aucun `*` seul, aucune origine en dur |
| `test_roles_et_clients_attendus` (existant, attente à mettre à jour) (dépend de Q14) | unitaire | même fichier | l'assertion `redirectUris == ["http://localhost/*"]` devient l'attente paramétrée ; le reste inchangé |
| `test_en_local_la_variable_du_front_vaut_localhost` (dépend de Q14) | unitaire | `compose.yaml` et `.env.example` | `compose.yaml` passe la variable à Keycloak ; `.env.example` la documente avec une valeur vide |
| `test_keycloak_de_prod_refuse_une_redirection_hors_du_domaine` (dépend de Q14) | intégration | Keycloak du cas E4 ci-dessus, variable = `https://demo.exemple.test` | `GET /auth/realms/billetterie/protocol/openid-connect/auth?client_id=frontend&redirect_uri=https://autre.exemple.test/&response_type=code&code_challenge=<généré>&code_challenge_method=S256` : page d'erreur « Invalid parameter: redirect_uri » (400) ; avec `redirect_uri=https://demo.exemple.test/` : 200, formulaire de connexion |

## CA1 : `https://<domaine>/api/v1/echos/bonjour` répond en HTTPS

Partie A : `test_traefik_de_prod_redirige_http_vers_https_et_route_l_api` (E3) et les cas de la
configuration TLS (E3). Partie B :

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_l_api_de_la_demo_repond_en_https_avec_un_certificat_valide` (dépend de Q9) | smoke | `DEMO_URL=https://<domaine>` lue dans l'environnement du poste, `GET /api/v1/echos/bonjour` sans jeton, vérification TLS active | handshake TLS réussi (certificat Let's Encrypt de production, valide pour le domaine) ; 401, `application/problem+json`, en-tête `WWW-Authenticate` commençant par `Bearer` |
| `test_la_demo_redirige_http_vers_https` | smoke | `GET http://<domaine>/api/v1/echos/bonjour`, sans suivre les redirections | 301 ou 308, `Location` = `https://<domaine>/api/v1/echos/bonjour` |
| `test_la_demo_n_expose_ni_le_tableau_de_bord_ni_d_autre_port` (dépend de Q8) | smoke | connexion TCP depuis le poste vers 8080, 5672, 8500, 15672, 5432 du domaine | toutes refusées ou expirées |
| Recette R1 : appel authentifié | recette manuelle | jeton du client `services` (Client Credentials, secret lu dans le gestionnaire du développeur), echo `bonjour` créé une fois comme donnée de démo | `GET https://<domaine>/api/v1/echos/bonjour` : 200, corps conforme à `EchoReponse`, `message` = `bonjour` |

## CA2 : `https://<domaine>/` affiche le front, qui se connecte au Keycloak de démo et appelle l'API sans erreur CORS

Partie A : E4 et E6. Partie B :

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_la_racine_de_la_demo_sert_le_front` | smoke | `GET https://<domaine>/` | 200, `text/html`, contient l'élément racine de l'application |
| `test_le_keycloak_de_la_demo_annonce_l_emetteur_du_domaine` | smoke | `GET https://<domaine>/auth/realms/billetterie/.well-known/openid-configuration` | 200, `issuer` = `https://<domaine>/auth/realms/billetterie`, `authorization_endpoint` commence par `https://<domaine>/auth/` |
| `test_la_demo_n_autorise_aucune_origine_etrangere` (dépend de Q19) | smoke | `OPTIONS https://<domaine>/api/v1/echos` avec `Origin: https://autre.exemple.test` | aucun en-tête `Access-Control-Allow-Origin` égal à cette origine |
| Recette R2 : connexion et appel depuis le navigateur | recette manuelle | navigation privée, utilisateur de démo `client.test` (mot de passe hors dépôt, Q14) | la page d'accueil s'affiche ; « Se connecter » mène à `https://<domaine>/auth/...` ; retour sur le front connecté (nom affiché) ; un appel à l'API (écran qui lit `/api/v1/...`) réussit ; console du navigateur sans erreur CORS ni contenu mixte ; onglet réseau : toutes les requêtes sur `https://<domaine>` |
| Recette R3 : redirection refusée hors domaine | recette manuelle | URL d'autorisation du client `frontend` avec `redirect_uri=https://autre.exemple.test/` | Keycloak affiche « Invalid parameter: redirect_uri » |
| Recette R4 (facultative) : parcours existant rejoué | parcours (existant) | `e2e/connexion.spec.ts` lancé depuis le poste avec l'URL de base `https://<domaine>` | parcours vert sans modification |

## CA3 : aucun secret dans le dépôt ni dans les journaux de CI

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_les_variables_sensibles_de_prod_sont_toutes_interpolees` | unitaire | `compose.prod.yaml` brut (sans interpolation) | toute variable d'environnement dont le nom contient `PASSWORD`, `PASS`, `SECRET`, `TOKEN`, `KEY`, `DATABASE_URL`, `DB_URL` ou `RABBITMQ_URL` a une valeur de forme `${NOM:?...}` ; aucune valeur littérale |
| `test_le_modele_d_environnement_de_prod_n_a_que_des_valeurs_vides` (dépend de Q3) | unitaire | `.env.prod.example` | chaque ligne `NOM=` sans valeur ; le fichier est suivi par Git (exception dans `.gitignore`) et `.env.prod` est ignoré |
| `test_le_workflow_ne_contient_aucune_valeur_secrete_en_clair` | unitaire | workflow de déploiement brut | toute entrée `password`, `key`, `token`, `ssh-key`, `known_hosts` vaut `${{ secrets.* }}` ou `${{ github.token }}` |
| `test_le_workflow_n_interpole_aucun_secret_dans_un_script` | unitaire | blocs `run:` du workflow | aucun `${{ secrets.` dans un `run:` (les secrets passent par `env:`) ; aucun `set -x`, `echo $` d'une variable secrète, ni `printenv`/`env` seul |
| `test_les_secrets_vont_au_vps_par_l_entree_standard` (dépend de Q13) | unitaire | étape SSH | `.env.prod` est transmis par l'entrée standard de `ssh` (ou `scp` d'un fichier temporaire), jamais en argument de commande |
| `test_les_secrets_de_clients_sont_des_variables`, `test_les_mots_de_passe_des_utilisateurs_sont_des_variables` (existants) | unitaire | `realm-billetterie.json` modifié | restent verts |
| Scan de secrets du dépôt (job CI) (dépend de Q17) | intégration (job CI) | gitleaks sur tout l'historique, à chaque PR | aucune fuite trouvée ; un faux secret injecté dans une branche de test jetable (`AKIA` + 16 caractères générés) fait échouer le job |
| Recette R5 : journaux du premier déploiement | recette manuelle | journaux téléchargés de l'exécution du workflow de déploiement (`gh run view --log`) | aucune occurrence du mot de passe Neon, de l'hôte Neon complet avec identifiants, de la clé SSH, du secret `services` ni des mots de passe de démo (recherche des valeurs réelles en local, jamais commitées) ; les secrets apparaissent masqués `***` |
| Recette R6 : journaux des conteneurs sur le VPS | recette manuelle | `docker compose logs` sur le VPS après R1 et R2 | aucun jeton, mot de passe ni URL de base avec identifiants (rule sécurité) |

## Recette manuelle de l'environnement (hors critères, à cocher par le développeur)

Ces étapes ne sont ni automatisables ni vérifiables par un agent ; elles conditionnent CA1 à CA3.

- [ ] VPS créé (Q2) ; architecture notée (`uname -m`).
- [ ] Pare-feu : seuls 22, 80 et 443 ouverts (`sudo ufw status` ou règles du fournisseur) ;
  depuis le poste, un balayage des autres ports échoue (complète
  `test_la_demo_n_expose_ni_le_tableau_de_bord_ni_d_autre_port`).
- [ ] SSH : `PasswordAuthentication no`, `PermitRootLogin no` ; connexion par clé avec
  l'utilisateur de déploiement, sans root (membre du groupe `docker`).
- [ ] Mises à jour de sécurité automatiques actives (`unattended-upgrades` ou équivalent).
- [ ] Domaine acheté (Q3) ; `dig +short <domaine> A` renvoie l'IP du VPS.
- [ ] Projet Neon `billetterie`, une base par service (et `keycloak`, Q10) ; aucune donnée
  réelle, volume sous 0,5 Go.
- [ ] Secrets GitHub posés (environnement `demo`, Q13) ; aucun dans le dépôt.
- [ ] Premier déploiement avec l'autorité ACME de staging, puis de production (Q7).
- [ ] `docker stats --no-stream` sur le VPS : chaque conteneur sous sa limite, total sous le
  budget (E2).
- [ ] Retour arrière essayé une fois avec un ancien tag (Q15).

## Couverture

| Critère | Cas |
|---|---|
| E1 | `test_la_configuration_de_prod_est_valide_avec_un_environnement_synthetique`, `test_sans_database_url_la_configuration_de_prod_est_refusee`, `test_la_prod_ne_contient_aucun_service_postgres`, `test_les_services_lisent_leur_base_dans_database_url`, `test_la_prod_tire_les_images_de_ghcr_sans_construire`, `test_la_prod_ne_garde_que_les_conteneurs_retenus`, `test_seul_traefik_publie_des_ports_et_seulement_80_et_443` |
| E2 | `test_chaque_conteneur_de_prod_a_une_limite_memoire`, `test_le_total_des_limites_memoire_tient_dans_le_budget_de_la_demo`, `test_la_heap_de_keycloak_tient_dans_sa_limite_memoire` |
| E3 | `test_la_configuration_statique_de_prod_redirige_web_vers_websecure`, `test_le_point_d_entree_https_utilise_le_resolveur_let_s_encrypt`, `test_les_certificats_acme_sont_stockes_sur_un_volume_persistant`, `test_l_adresse_acme_vient_de_l_environnement`, `test_le_tableau_de_bord_de_traefik_est_coupe_en_prod`, `test_les_tags_consul_visent_le_point_d_entree_https_en_prod`, `test_les_definitions_consul_de_keycloak_et_du_front_suivent_le_point_d_entree_de_prod`, `test_traefik_de_prod_redirige_http_vers_https_et_route_l_api` |
| E4 | `test_keycloak_de_prod_demarre_en_mode_production`, `test_keycloak_de_prod_publie_l_emetteur_https_du_domaine_sous_auth`, `test_le_verificateur_et_echo_attendent_l_emetteur_du_domaine`, `test_keycloak_de_prod_lit_sa_base_dans_l_environnement`, `test_keycloak_en_mode_production_derriere_le_proxy_annonce_l_emetteur_https`, `test_le_front_de_prod_est_route_sur_la_racine_hors_api_et_auth`, `test_le_front_de_prod_n_embarque_aucune_url_d_api_ou_de_keycloak_absolue` |
| E5 | `test_le_deploiement_ne_se_declenche_que_manuellement`, `test_le_deploiement_ne_part_que_de_main`, `test_le_deploiement_construit_echo_le_verificateur_et_le_front_pour_amd64_et_arm64`, `test_le_deploiement_publie_les_images_sur_ghcr`, `test_le_deploiement_applique_les_migrations_avant_de_relancer_les_services`, `test_le_deploiement_relance_la_plateforme_par_ssh_avec_compose_pull_et_up`, `test_la_cle_ssh_et_l_hote_viennent_des_secrets`, `test_le_deploiement_accepte_un_tag_pour_revenir_en_arriere`, `test_les_jobs_de_test_de_la_ci_ne_recoivent_aucun_secret` |
| E6 | `test_les_redirect_uris_du_client_frontend_sont_parametrees_par_le_domaine`, `test_roles_et_clients_attendus`, `test_en_local_la_variable_du_front_vaut_localhost`, `test_keycloak_de_prod_refuse_une_redirection_hors_du_domaine` |
| CA1 | `test_traefik_de_prod_redirige_http_vers_https_et_route_l_api`, `test_l_api_de_la_demo_repond_en_https_avec_un_certificat_valide`, `test_la_demo_redirige_http_vers_https`, `test_la_demo_n_expose_ni_le_tableau_de_bord_ni_d_autre_port`, recette R1 |
| CA2 | `test_keycloak_en_mode_production_derriere_le_proxy_annonce_l_emetteur_https`, `test_keycloak_de_prod_refuse_une_redirection_hors_du_domaine`, `test_la_racine_de_la_demo_sert_le_front`, `test_le_keycloak_de_la_demo_annonce_l_emetteur_du_domaine`, `test_la_demo_n_autorise_aucune_origine_etrangere`, recettes R2, R3, R4 |
| CA3 | `test_les_variables_sensibles_de_prod_sont_toutes_interpolees`, `test_le_modele_d_environnement_de_prod_n_a_que_des_valeurs_vides`, `test_le_workflow_ne_contient_aucune_valeur_secrete_en_clair`, `test_le_workflow_n_interpole_aucun_secret_dans_un_script`, `test_les_secrets_vont_au_vps_par_l_entree_standard`, `test_les_secrets_de_clients_sont_des_variables`, `test_les_mots_de_passe_des_utilisateurs_sont_des_variables`, scan de secrets (job CI), recettes R5, R6 |
