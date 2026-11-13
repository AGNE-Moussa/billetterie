# Service notifications

Service créé sur le modèle de `services/echo/` (voir son README pour les conventions). Envoie
les billets par e-mail (BIL-009).

- Préfixe de routes annoncé à Consul et Traefik : `/api/v1/notifications`.
- Base PostgreSQL : `notifications`.
- Route : `GET /health` (santé de l'instance et de sa base, appelée par Consul) ; via
  Traefik, `GET /api/v1/notifications/health` (jeton requis, réécrit en `/health` par le
  routeur `notifications-sante` de `commun.registre.tags_sante_traefik`).
- Consommateurs (`RABBITMQ_URL`) : `notifications.order-confirmed` (destinataire de chaque
  commande, `destinataires_commande`) et `notifications.ticket-issued` (un e-mail par billet,
  QR joint en PNG ; historique `envois`, `UNIQUE (evenement_id, commande_id)`). Le service ne
  publie rien : ni relais d'outbox.
- Envoi d'un billet, dans la transaction du consommateur : commande inconnue (`order.confirmed`
  pas encore reçu) = exception, nouvel essai puis `notifications.ticket-issued.dlq` ; `email`
  NULL (revendeur) = rien ; sinon `INSERT INTO envois ... ON CONFLICT DO NOTHING RETURNING`,
  puis l'envoi SMTP seulement si la ligne est nouvelle, puis le commit. Un échec SMTP annule
  tout (nouvel essai). Risque résiduel : SMTP réussi puis commit perdu = un doublon possible.
- SMTP : `SMTP_HOTE` (`mailpit`), `SMTP_PORT` (1025), `SMTP_DELAI` (5 s, strictement
  positif : borne la connexion et chaque lecture), `SMTP_EXPEDITEUR`
  (`billetterie@exemple.test`) ; envoi `smtplib` dans un fil séparé. En local, Mailpit (boîte
  sur http://127.0.0.1:8025).
- Migrations : `0001_initiale` (vide), `0002_creer_tables_messagerie`,
  `0003_creer_tables_destinataires_envois`, lancées une fois par le conteneur
  `notifications-migrations`. `destinataires_commande.seance_id` n'a pas de clé étrangère vers
  `infos_seances` (H6 de BIL-009).
- Contrat : `openapi.yaml`, vérifié par `pytest -m contract`.
- Observabilité (`/metrics`, traces) et revérification des jetons (`installer_auth`, `JWT_*`)
  comme echo.
