# Service billets

Service créé au ticket BIL-001 sur le modèle de `services/echo/` (voir son README pour les
conventions). BIL-006 : places des séances et verrou d'une place pendant l'achat.

- Préfixes de routes annoncés à Consul et Traefik : `/api/v1/seats` et `/api/v1/tickets`
  (BIL-021), sur la chaîne `standard@file` et sur l'hôte des revendeurs `HOTE_PARTENAIRES`
  (`partenaires@file`, quota par jeton, BIL-012). La santé reste sous `/api/v1/seats/health`.
- Base PostgreSQL : `billets` ; deux instances en local (`billets-1`, `billets-2`), qui
  partagent la base et le Redis.
- Routes :
  - `GET /health` : santé de l'instance et de sa base, jamais de Redis (Redis est partagé :
    retirer les instances de Consul n'aiderait pas) ;
  - `GET /api/v1/seats?seance_id=&page=&size=` (`listerPlaces`, publique : préfixe
    `GET /api/v1/seats` dans `ROUTES_PUBLIQUES`, santé `/api/v1/seats/health` comprise) ;
    `disponible` est faux si la place porte un verrou ou un billet, quel que soit son statut ;
  - `PUT /api/v1/seats/{place_id}/lock` (`verrouillerPlace`, scope `seats:lock`, client
    `services`) ;
  - `GET /api/v1/tickets?commande_id=&page=&size=` (`listerBillets`) et
    `GET /api/v1/tickets/{billet_id}` (`lireBillet`), scope `tickets:read` (client et
    revendeur, BIL-021) : toujours filtrés par l'appelant du jeton (`billets.client` = `sub`),
    jamais par un paramètre ; `commande_id` facultatif restreint en plus à une commande (une
    commande d'un autre appelant donne une page vide) ; billet d'un autre appelant : 404
    `TICKET_NOT_FOUND`. Ordre : `emis_le` décroissant, puis identifiant. `rang` et `numero`
    sont lus par jointure sur `places`, dans la même requête ; base injoignable : 503
    `BASE_INDISPONIBLE`.
- Ordre des places : rang en tri binaire (`COLLATE "C"`, `A` < `AA` < `B` ; `10` < `9`), puis
  numéro, puis identifiant.
- Verrou d'une place : Redis, clé `place:<seance_id>:<place_id>`, valeur `commande_id`
  (`domaine/verrous.py` pour le port, `infra/verrous.py` pour Redis). Trois scripts Lua,
  atomiques :
  - poser : `SET NX PX` ; si la commande détient déjà le verrou, il est prolongé sans jamais
    être raccourci (`max(PTTL restant, durée)`) ; une autre commande reçoit 409
    `SEAT_ALREADY_TAKEN` ;
  - confirmer (`confirmation: true`) : repose la durée de confirmation, seulement pour le
    détenteur ; sinon 409, et aucun verrou n'est créé ;
  - libérer (fonction du magasin, sans route) : compare puis supprime ; un ancien détenteur ne
    supprime jamais le verrou d'une autre commande.
- `expire_le` = instant de la requête (fixé avant les lectures en base) + durée restante
  réellement posée (PTTL rendu par le script). Elle précède la fin réelle du verrou de la
  latence de la requête : légèrement prudente, jamais en retard.
- Ordre des contrôles du verrou : 401, 403, 422, 404 `SEAT_NOT_FOUND` (place absente de la
  séance, lu en base), 409 si un billet existe (lu en base), puis le verrou Redis.
  `uq_billets_place` garantit en base qu'une place n'est vendue qu'une fois.
- Indisponibilités : Redis injoignable ou plus lent que `DELAI_REDIS` donne 503
  `VERROU_INDISPONIBLE` (jamais de 200 sans verrou) ; base injoignable, 503
  `BASE_INDISPONIBLE`. Aucune nouvelle tentative côté client.
  - Un 503 `VERROU_INDISPONIBLE` ne prouve pas que le verrou est absent : si le délai est
    dépassé après l'exécution du script, le verrou est posé pour la commande. L'appelant
    (Commandes) rappelle avec la même `commande_id` : l'appel est idempotent et répond 200
    avec l'expiration réelle. Sans rappel, la place reste prise pour cette commande jusqu'à
    `DUREE_VERROU_RESERVATION` au plus (échec fermé, sans double vente).
  - Redis doit rester en politique d'éviction `noeviction` (sans `maxmemory-policy` qui
    évince) : les verrous partagent la base Redis 0 avec le cache du catalogue, et une
    éviction (`allkeys-lru`, par exemple) ferait disparaître des verrous en silence (plus de
    409 garanti ; seule `uq_billets_place` empêcherait encore la double vente). Avant tout
    réglage d'éviction pour le cache, séparer les verrous (autre instance Redis).
- Consommateur : `ticketing.show.scheduled` (file `billets.show-scheduled`, DLQ
  `billets.show-scheduled.dlq`), idempotent (`commun.consommateurs`) ; crée les places,
  numéros de 1 à `nombre_places` par rang, par `INSERT ... ON CONFLICT DO NOTHING` (une séance
  republiée ne crée aucun doublon et ne supprime rien), par lots de 1 000 places (limite de
  32 767 paramètres d'asyncpg) dans la même transaction que `messages_traites`.
- Consommateur : `ticketing.order.confirmed` (file `billets.order-confirmed`, DLQ
  `billets.order-confirmed.dlq`, BIL-009) ; émission tout ou rien par commande, dans la
  transaction de `messages_traites` :
  - séance présente dans `seances_annulees` : aucun billet, `ticketing.ticket.rejected`
    `SEANCE_ANNULEE` (toutes les places) ;
  - sinon un billet `EMIS` par ligne, par `INSERT ... ON CONFLICT ON CONSTRAINT
    uq_billets_place DO NOTHING RETURNING` (places triées : pas d'interblocage) ; jamais de
    lecture préalable des places. Une place prise (même par une transaction concurrente,
    attendue jusqu'à son commit) n'est pas insérée : les billets tout juste insérés de la
    commande sont supprimés dans la même transaction et `ticketing.ticket.rejected`
    `PLACE_DEJA_VENDUE` part avec les places en conflit. Pas de SAVEPOINT : ses lignes
    porteraient l'`xmin` d'une sous-transaction ;
  - places en conflit qui portent déjà un billet de la même commande (republication sous un
    autre identifiant) : rien de plus, journal `INFO` ;
  - place inconnue (`fk_billets_place`) : exception, trois livraisons puis DLQ ;
  - un `ticketing.ticket.issued` par billet (outbox), sans e-mail (v1) ;
  - verrou consultatif **partagé** de la séance (`commun.verrou_seance`,
    `pg_advisory_xact_lock_shared`) pris avant la lecture de `seances_annulees`, tenu jusqu'au
    commit (Q3 de BIL-011) ;
  - après le commit (point d'accroche `apres_commit` de `commun.consommateurs`, aussi pour un
    message déjà traité) : suppression des verrous de la commande par le script « comparer
    puis supprimer » ; Redis injoignable = journal `WARNING`, le message reste traité.
- Consommateur : `ticketing.show.cancelled` (file `billets.show-cancelled`, DLQ
  `billets.show-cancelled.dlq`, BIL-011) : sous le verrou consultatif **exclusif** de la
  séance (une émission en cours finit avant, une émission qui arrive après lit la séance
  annulée), inscrit la séance dans `seances_annulees` (`ON CONFLICT DO NOTHING`, `annulee_le`
  d'origine conservée), puis passe ses billets `EMIS` en `ANNULE` (`qr_code` conservé), dans la
  transaction de `messages_traites`. Places et billets annulés gardés : la place reste
  indisponible (`uq_billets_place` sans condition). Le statut n'est pas encore lu au contrôle
  d'un QR (route de scan, V3).
- QR code (`domaine/qr.py`) : `<billet_id>.<signature>`, HMAC-SHA256 de l'identifiant en
  base64url sans remplissage ; `verifier_qr(contenu)` recalcule la signature (comparaison à
  temps constant) et rend l'identifiant, ou lève `QrInvalide`. Elle ne lit pas la base : le
  refus d'un billet annulé ou déjà scanné relèvera de la route de scan (V3).
- Configuration : `DATABASE_URL`, `REDIS_URL` (obligatoire), `QR_CLE_SIGNATURE` (obligatoire,
  au moins 32 caractères, dans `.env`, jamais dans le dépôt), `RABBITMQ_URL` (facultatif, sans
  URL pas de consommateur), `DUREE_VERROU_RESERVATION` (600 s), `DUREE_VERROU_CONFIRMATION`
  (3600 s), entiers strictement positifs, `DELAI_REDIS` (0,5 s), `DELAI_BASE` (5 s).
- Migrations : `0001` (vide), `0002` (messagerie, commun.outbox), `0003` (places, billets ;
  contraintes `uq_places_seance_rang_numero`, `uq_places_seance_id`, `uq_billets_place`,
  `fk_billets_place` composite (`seance_id`, `place_id`) vers `places (seance_id, id)` : un
  billet porte la séance de sa place, `ck_billets_statut`), `0004` (`seances_annulees`,
  remplie par `ticketing.show.cancelled` depuis BIL-011), lancées une fois par le conteneur
  `billets-migrations` ; Alembic ne lit que `DATABASE_URL`.
- Contrat : `openapi.yaml`, vérifié par `pytest -m contract`.

## Deux instances (BIL-013)

- **Instances nommées plutôt que `deploy.replicas: 2`** : le compose déclare `billets-1` et
  `billets-2` (ancre `*billets-instance`), comme echo et Commandes. Chaque instance s'annonce à
  Consul avec son nom réseau (`INSTANCE`), d'où un identifiant unique
  (`commun.registre.identifiant_instance` : `billets-billets-1-8000`, `billets-billets-2-8000`)
  et un check HTTP qui vise cette instance précise. Avec `deploy.replicas`, les répliques
  partageraient la même variable `INSTANCE` : même identifiant Consul (la seconde écraserait la
  première dans le registre), même adresse annoncée (résolue au hasard par le DNS de Docker),
  et des journaux, métriques et verrous de tâche impossibles à attribuer à une instance.
- Répartition : les deux instances portent le même nom de service Consul (`billets`) et les
  mêmes tags ; Traefik (`consulCatalog`) en fait un seul service à deux serveurs, en
  round-robin, et n'envoie du trafic qu'aux instances au check `passing` (`strictChecks`).
  CA1 se vérifie après `make up` : `http://127.0.0.1:8500/ui/dc1/services/billets/instances`,
  ou `make test-smoke` (`test_les_cinq_services_sont_verts_dans_consul` attend deux instances
  `passing`). Répartition visible dans Grafana (`make observabilite`, panneau « Répartition par
  instance »).
- Aucun état métier en mémoire de processus : verrous des places dans Redis (scripts Lua
  atomiques), unicité en base (`uq_billets_place`), verrou consultatif PostgreSQL de la séance
  (`commun.verrou_seance`), idempotence des consommateurs en base (`messages_traites`). Les
  files RabbitMQ (`billets.*`) sont partagées : chaque message va à une seule des deux instances.
  Le relais de l'outbox tourne dans chaque instance ; `FOR UPDATE SKIP LOCKED` réserve chaque
  ligne à un seul relais (aucune double publication hors arrêt brutal, couvert par
  l'idempotence des consommateurs). L'ordre global de publication n'est plus garanti entre les
  deux relais : les consommateurs ne le supposent pas (rule `evenements.md`). Seuls restent en
  mémoire des états techniques propres à l'instance : clés JWKS en cache, disjoncteurs des
  appels sortants, métriques Prometheus, connexion au broker.

### Rejouer les tests de concurrence BIL-007 avec deux instances

`make test-concurrence` (Docker requis, Testcontainers) joue tous les tests marqués
`concurrence`. Ils montent déjà **deux instances** de chaque service (deux applications
`creer_app` distinctes, sur la même base PostgreSQL et le même Redis réels) et répartissent les
appels entre elles :

- `services/billets/tests/integration/test_concurrence_ventes.py` : 100 verrouillages
  simultanés de la même place, répartis sur `billets-1` et `billets-2`, puis la contrainte
  `uq_billets_place` seule ;
- `services/billets/tests/integration/test_emission_concurrence.py` : émission concurrente ;
- `services/commandes/tests/integration/test_concurrence_commandes.py`,
  `test_concurrence_meme_commande_postgres_redis.py` et
  `test_expiration_concurrence_postgres_redis.py` : commandes, paiement et tâche d'expiration
  disputés entre `commandes-1` et `commandes-2`.

Pour ne rejouer que BIL-007 : `uv run pytest services/billets/tests/integration/test_concurrence_ventes.py -m concurrence`.
Contre la plateforme Docker Compose elle-même (deux conteneurs derrière Traefik), il n'existe
pas de test automatisé : `make up`, puis vérifier Consul et le panneau Grafana ci-dessus.
