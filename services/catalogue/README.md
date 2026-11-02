# Service catalogue

Événements, lieux et séances (BIL-004), sur le modèle de `services/echo/` (voir son README pour
les conventions).

- Préfixes de routes annoncés à Consul et Traefik : `/api/v1/events`, `/api/v1/venues`,
  `/api/v1/shows`. Lectures publiques (`ROUTES_PUBLIQUES` du vérificateur dans `compose.yaml`) ;
  créations réservées au scope `events:write` (admin).
- Portée de `ROUTES_PUBLIQUES` : ce sont des préfixes. Toute route `GET`, présente ou future,
  sous `/api/v1/events`, `/api/v1/venues` ou `/api/v1/shows` est publique à la gateway. Une
  future lecture réservée (à l'admin par exemple) doit donc être protégée dans le service
  (`AppelantDep`, `exige_scopes`, `exige_role`), qui revérifie toujours le jeton ; la gateway
  seule ne la protège pas.
- Base PostgreSQL : `catalogue`. Tables `evenements`, `lieux`, `seances`, `categories`, `rangs`
  (`docs/modele-donnees.md`), plus `outbox` et `messages_traites` (`commun.outbox`).
- Migrations : `alembic.ini`, `alembic/versions/` (`0001` vide, `0002` tables du catalogue et
  de messagerie), lancées une fois par le conteneur `catalogue-migrations`.
- Événement publié : `ticketing.show.scheduled` à chaque séance programmée, rangé dans l'outbox
  dans la transaction de la séance, puis publié par le `RelaisOutbox` (`RABBITMQ_URL`).
- Base injoignable : 503 `BASE_INDISPONIBLE` ; attente bornée par `DELAI_BASE` (secondes,
  5 par défaut) pour la connexion et chaque requête.
- Cache Redis des lectures (BIL-005), actif si `REDIS_URL` est défini (sur la plateforme :
  `redis://redis:6379/0`) ; sans URL, les lectures vont en base comme avant. Les 7 lectures
  publiques gardent deux copies du corps JSON exact : une copie fraîche (`CACHE_DUREE_FRAICHE`,
  30 s), servie sans interroger la base, et une copie de secours (`CACHE_DUREE_SECOURS`,
  86400 s), servie avec `X-Cache-Stale: true` seulement si la base est injoignable (503
  `BASE_INDISPONIBLE` sinon). Seuls les 200 sont mis en cache ; un 404, un 422 ou un 500 ne
  l'est jamais, et seule la base injoignable déclenche le secours. `/health` ignore le cache.
  Code : `api/cache_lectures.py` (cache-aside, invalidation), `domaine/cache.py` (port
  `CacheCatalogue`) et `infra/cache.py` (redis-py).
- Clés Redis : `catalogue:cache:v1:<fraiche|secours>:<operationId>:[g<génération>:]<sha256 des
  paramètres>`, toujours avec expiration ; `catalogue:generation:<famille>` (familles
  `evenements`, `lieux`, `seances:<evenement_id>`), compteurs sans expiration, volontairement
  hors du préfixe `catalogue:cache:` : un compteur qui expirerait repartirait de 0 et rendrait
  de nouveau accessibles d'anciennes copies de secours. Ces compteurs supposent la politique
  d'éviction `noeviction` (valeur par défaut, `compose.yaml` ne fixe pas `maxmemory`) : avec
  une politique `allkeys-*`, un compteur évincé repartirait de 0 ; ils s'accumulent aussi, un
  par événement ayant reçu une séance (`seances:<evenement_id>`), sans purge.
- Invalidation : après un 201 commité, `creerEvenement` incrémente `evenements`, `creerLieu`
  `lieux`, `creerSeance(E)` `seances:E` et `evenements` (filtres ville et dates). Les copies
  des anciennes générations deviennent inaccessibles puis expirent. Une lecture lit la
  génération avant la base et n'écrit que sous elle : une lecture commencée avant une création
  ne remet pas l'ancienne liste en cache. Les détails ne sont jamais invalidés (aucune route ne
  les modifie).
- Redis injoignable ou lent : chaque appel est borné par `DELAI_REDIS` (0,5 s) ; la requête
  continue sans cache (jamais de 5xx dû à Redis), avec un avertissement journalisé sans URL.
  Au premier échec, Redis est coupé pour le reste de la requête : plus aucun appel, un seul
  avertissement par requête. Un compteur de génération non entier est traité comme Redis
  injoignable.
- Limites connues :
  - Redis en panne pendant une création admin : la création répond 201 mais l'invalidation
    échoue (journal d'erreur). Redis étant persistant, à son retour les anciennes copies
    fraîches peuvent encore servir jusqu'à 30 s et les copies de secours jusqu'à 24 h.
  - Par la gateway, CA2 n'est pas tenu : base arrêtée, `/health` répond 503, Consul passe
    l'instance en « critical » et Traefik la retire ; les lectures reçoivent alors le 503 de
    Traefik. Le secours n'est servi qu'en appel direct du service (ticket de suivi : check
    Consul sur une route de vivacité qui ne teste pas la base).
  - Base injoignable : chaque lecture attend `DELAI_BASE` avant de servir le secours (pas de
    disjoncteur).
  - `python -m catalogue.demo` écrit directement en base, sans invalidation : les nouvelles
    données apparaissent sous 30 s, et une copie de secours d'avant le chargement peut
    resservir d'anciennes listes. À charger sur une plateforme neuve.
- Santé : `GET /health` (appelée par Consul) ; via Traefik, `GET /api/v1/events/health`
  (réécrit en `/health` par le routeur `catalogue-sante`). Cette santé est publique via la
  gateway, sans jeton, car elle tombe sous le préfixe `GET /api/v1/events` (décision Q4, option
  a) ; elle ne renvoie que `{"statut": "ok"}`.
- Jeu de démonstration : `python -m catalogue.demo` (`DATABASE_URL` requis), idempotent (UUID
  fixes), dates relatives au jour du chargement ; sur la plateforme locale :
  `docker compose run --rm catalogue-migrations python -m catalogue.demo`.
- Contrat : `openapi.yaml`, vérifié par `pytest -m contract`.
