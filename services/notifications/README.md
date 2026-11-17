# Service notifications

Service créé sur le modèle de `services/echo/` (voir son README pour les conventions). Envoie
les billets par e-mail (BIL-009), prévient de l'annulation d'une séance et du remboursement
(BIL-011).

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
- Annulation d'une séance (BIL-011) :
  - `notifications.show-cancelled` (`ticketing.show.cancelled`) : un e-mail d'annulation par
    commande de la séance dont le destinataire est connu au moment du traitement ; `email` NULL
    (revendeur) : rien. Chaque commande a sa propre transaction, à part de celle du message :
    inscription dans `envois` (une ligne par commande), envoi SMTP, puis commit. Un échec SMTP
    n'annule que la commande en cours et fait échouer le message (nouvel essai) ; les
    commandes déjà servies, inscrites, ne reçoivent rien de plus. La séance est citée par son
    identifiant (`infos_seances` n'est pas remplie).
  - `notifications.payment-refunded` (`ticketing.payment.refunded`) : un e-mail de
    remboursement (montant en euros) ; commande inconnue = exception, nouvel essai puis
    `notifications.payment-refunded.dlq` ; revendeur : rien.
  - Journaux : identifiants seulement, jamais d'adresse.
  - **Limites connues (Q6 de BIL-011)** : un acheteur dont `ticketing.order.confirmed` arrive
    après le traitement de `ticketing.show.cancelled` ne reçoit pas l'e-mail d'annulation,
    seulement celui du remboursement. Une commande remboursée sans avoir jamais été confirmée
    (paiement accepté puis remboursé avant la confirmation, Q4) n'a pas de destinataire : son
    `ticketing.payment.refunded` finit en `notifications.payment-refunded.dlq` après trois
    essais, sans e-mail. E-mails d'annulation : un SMTP réussi suivi d'un commit perdu pour
    cette commande peut donner un doublon pour elle seule (même risque résiduel que le billet) ;
    un message qui finit en file d'erreur laisse servies les commandes déjà inscrites.
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
