# Service billets

Service créé au ticket BIL-001 sur le modèle de `services/echo/` (voir son README pour les
conventions). BIL-006 : places des séances et verrou d'une place pendant l'achat.

- Préfixe de routes annoncé à Consul et Traefik : `/api/v1/seats`.
- Base PostgreSQL : `billets` ; deux instances en local (`billets-1`, `billets-2`), qui
  partagent la base et le Redis.
- Routes :
  - `GET /health` : santé de l'instance et de sa base, jamais de Redis (Redis est partagé :
    retirer les instances de Consul n'aiderait pas) ;
  - `GET /api/v1/seats?seance_id=&page=&size=` (`listerPlaces`, publique : préfixe
    `GET /api/v1/seats` dans `ROUTES_PUBLIQUES`, santé `/api/v1/seats/health` comprise) ;
    `disponible` est faux si la place porte un verrou ou un billet, quel que soit son statut ;
  - `PUT /api/v1/seats/{place_id}/lock` (`verrouillerPlace`, scope `seats:lock`, client
    `services`).
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
- Configuration : `DATABASE_URL`, `REDIS_URL` (obligatoire), `RABBITMQ_URL` (facultatif, sans
  URL pas de consommateur), `DUREE_VERROU_RESERVATION` (600 s), `DUREE_VERROU_CONFIRMATION`
  (3600 s), entiers strictement positifs, `DELAI_REDIS` (0,5 s), `DELAI_BASE` (5 s).
- Migrations : `0001` (vide), `0002` (messagerie, commun.outbox), `0003` (places, billets ;
  contraintes `uq_places_seance_rang_numero`, `uq_places_seance_id`, `uq_billets_place`,
  `fk_billets_place` composite (`seance_id`, `place_id`) vers `places (seance_id, id)` : un
  billet porte la séance de sa place, `ck_billets_statut`), lancées une fois par le conteneur
  `billets-migrations` ; Alembic ne lit que `DATABASE_URL`.
- Contrat : `openapi.yaml`, vérifié par `pytest -m contract`.
