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
- Santé : `GET /health` (appelée par Consul) ; via Traefik, `GET /api/v1/events/health`
  (réécrit en `/health` par le routeur `catalogue-sante`). Cette santé est publique via la
  gateway, sans jeton, car elle tombe sous le préfixe `GET /api/v1/events` (décision Q4, option
  a) ; elle ne renvoie que `{"statut": "ok"}`.
- Jeu de démonstration : `python -m catalogue.demo` (`DATABASE_URL` requis), idempotent (UUID
  fixes), dates relatives au jour du chargement ; sur la plateforme locale :
  `docker compose run --rm catalogue-migrations python -m catalogue.demo`.
- Contrat : `openapi.yaml`, vérifié par `pytest -m contract`.
