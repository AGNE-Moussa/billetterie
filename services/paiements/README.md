# Service paiements

Service sur le modèle de `services/echo/` (voir son README pour les conventions). BIL-008 :
paiement simulé d'une commande, appelé par Commandes seulement.

- Préfixe de routes annoncé à Consul et Traefik : `/api/v1/payments`.
- Base PostgreSQL : `paiements` ; une instance en local (`paiements-1`).
- Routes : `GET /health` ; `POST /api/v1/payments` (`creerPaiement`, scope `payments:write`,
  client `services` seulement, `Idempotency-Key` obligatoire égal à `commande_id`, sinon 422) ;
  `GET /api/v1/payments/{commande_id}` (`lirePaiement`, même scope, lecture seule : 200 quel que
  soit le statut, 404 `PAYMENT_NOT_FOUND`, ne crée jamais de paiement).
- Un seul paiement par commande (`uq_paiements_commande_id`) : un paiement enregistré se rejoue
  (201, ou 402 s'il est refusé) quelle que soit la carte, même après l'annulation de la séance ;
  un autre montant ou une autre séance répond 409 `PAYMENT_ALREADY_EXISTS`. Des requêtes
  simultanées insèrent par `ON CONFLICT DO NOTHING` puis relisent le paiement gagnant.
- Séance présente dans `seances_annulees` et aucun paiement enregistré : 409 `SHOW_CANCELLED`,
  sans ligne. Le paiement prend le verrou consultatif **partagé** de la séance
  (`commun.verrou_seance`, `pg_advisory_xact_lock_shared`) avant de lire `seances_annulees`,
  jusqu'au commit de son insertion (Q2 de BIL-011).
- Événements (BIL-011, `RABBITMQ_URL` ; sans URL, ni consommateur ni relais) :
  - `paiements.show-cancelled` (`ticketing.show.cancelled`) : sous le verrou **exclusif** de la
    séance, inscrit la séance dans `seances_annulees` (`ON CONFLICT DO NOTHING`), puis passe
    chaque paiement `ACCEPTE` de la séance en `REMBOURSE` (`UPDATE ... WHERE statut =
    'ACCEPTE'`) et publie un `ticketing.payment.refunded` par paiement, dans la même
    transaction. Un paiement en cours finit donc avant (il est remboursé) ou lit la séance
    annulée (409).
  - `paiements.ticket-rejected` (`ticketing.ticket.rejected`, tout motif) : rembourse le paiement
    `ACCEPTE` de la commande, même passage conditionnel. Paiement absent, refusé ou déjà
    remboursé : rien.
  - Un paiement n'est remboursé qu'une fois, quelles que soient les sources et leur ordre (le
    passage conditionnel sur la ligne départage les traitements simultanés).
  - Remboursement simulé : aucun appel externe. Un paiement remboursé se rejoue (201, statut
    `REMBOURSE`), sans nouveau débit.
- Carte de test `4000000000000002` refusée (paiement `REFUSE` enregistré), tout autre numéro de
  16 chiffres accepté ; le numéro n'est ni journalisé ni enregistré.
- Base injoignable : 503 `BASE_INDISPONIBLE` après `DELAI_BASE` secondes (5 par défaut).
- Migrations : `0001` (vide), `0002` (outbox, messages_traites, utilisées depuis BIL-011),
  `0003` (paiements, seances_annulees), lancées une fois par le conteneur
  `paiements-migrations`.
- Contrat : `openapi.yaml`, vérifié par `pytest -m contract`.
