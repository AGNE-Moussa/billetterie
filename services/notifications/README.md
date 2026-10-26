# Service notifications

Squelette (BIL-001) sur le modèle de `services/echo/` (voir son README pour les conventions) :
aucune logique métier pour l'instant.

- Préfixe de routes annoncé à Consul et Traefik : `/api/v1/notifications`.
- Base PostgreSQL : `notifications`.
- Route : `GET /health` (santé de l'instance et de sa base, appelée par Consul) ; via
  Traefik, `GET /api/v1/notifications/health` (jeton requis, réécrit en `/health` par le
  routeur `notifications-sante` de `commun.registre.tags_sante_traefik`).
- Migrations : `alembic.ini`, `alembic/versions/0001_initiale.py` (vide), lancées une fois par
  le conteneur `notifications-migrations`.
- Contrat : `openapi.yaml`, vérifié par `pytest -m contract`.
- Observabilité (`/metrics`, traces) et revérification des jetons (`installer_auth`, `JWT_*`)
  comme echo ; ni RabbitMQ ni outbox tant que le service ne publie ni ne consomme d'événement.
