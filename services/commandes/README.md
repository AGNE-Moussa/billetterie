# Service commandes

Service sur le modèle de `services/echo/` (voir son README pour les conventions). BIL-008 :
passer commande et payer.

- Préfixe de routes annoncé à Consul et Traefik : `/api/v1/orders`.
- Base PostgreSQL : `commandes` ; deux instances en local (`commandes-1`, `commandes-2`).
- Routes : `GET /health` ; `POST /api/v1/orders` (`creerCommande`, scope `orders:write`,
  `Idempotency-Key` facultatif), `GET /api/v1/orders` (`listerCommandes`, `orders:read`),
  `GET /api/v1/orders/{commande_id}` (`lireCommande`), `POST
  /api/v1/orders/{commande_id}/payment` (`payerCommande`, `orders:write`). Toute lecture filtre
  par le sujet du jeton ; la commande d'un autre répond 404 `ORDER_NOT_FOUND`.
- Parcours de `creerCommande` : clé d'idempotence réservée (verrou consultatif sur client et
  clé, 409 `REQUEST_IN_PROGRESS` s'il est pris, rejeu d'une requête terminée en 200) ; séance lue
  dans Catalogue ; plafond compté et commande `EN_ATTENTE` créée sous
  `pg_advisory_xact_lock(client, seance_id)` ; verrou de réservation de chaque place au nom de
  la commande (prix de sa catégorie) ; reverrouillage en durée de confirmation ; paiement
  (`Idempotency-Key` = `commande_id`) ; `CONFIRMEE` et `ticketing.order.confirmed` dans la même
  transaction.
- Échecs : place prise ou inconnue, Billets indisponible pendant la réservation, place perdue au
  reverrouillage, paiement refusé, séance annulée chez Paiements : commande `EXPIREE` et
  `ticketing.order.expired` (toutes les places de la commande). Billets indisponible au
  reverrouillage ou Paiements indisponible : 503 `SERVICE_INDISPONIBLE`, commande `EN_ATTENTE`,
  nouvel essai par `payerCommande`.
- Concurrence sur une même commande : chaque transition de statut relit la commande sous
  `FOR UPDATE` et n'a lieu que depuis `EN_ATTENTE` ; sinon aucun appel à Paiements, et une
  commande déjà confirmée est rendue sans second `ticketing.order.confirmed`.
- `payerCommande` : 409 `REQUEST_IN_PROGRESS` tant que la réservation de `creerCommande` n'est
  pas terminée (`expire_le` inconnu), sans appel à Paiements ; séance inconnue de Catalogue :
  404 `SHOW_NOT_FOUND` ; séance annulée ou commencée : 409, commande `EXPIREE` et
  `ticketing.order.expired`.
- `ticketing.order.expired` porte `remboursement_du: true` si Paiements a déjà accepté le
  paiement de la commande : avant d'expirer une commande déjà envoyée à Paiements (colonne
  `paiement_demande`, posée juste avant l'appel), Commandes **lit** son paiement
  (`GET /api/v1/payments/{commande_id}`, `lirePaiement`, jamais de `POST`) ; `REFUSE`,
  `REMBOURSE` ou 404 : pas de champ. Paiements injoignable à cette lecture : 503
  `SERVICE_INDISPONIBLE`, commande `EN_ATTENTE`.
- **Limite connue, non traitée par BIL-008** : si une requête expire la commande pendant le
  `POST` de paiement d'une autre requête, le client est **débité sans billet et sans
  remboursement automatique**. Aucun `ticketing.order.expired` ne porte `remboursement_du` pour
  ce débit (l'événement est déjà parti) ; le seul signal est un journal au niveau erreur
  (`commande_id` seulement). À reprendre dans le ticket de remboursement, qui rapprochera les
  paiements `ACCEPTE` des commandes `EXPIREE` (ticket pas encore créé).
- Clés d'idempotence : verrou consultatif tenu pendant la requête sur un moteur dédié (pool de
  5 connexions sans débordement, attente bornée par `DELAI_BASE`, puis 503
  `BASE_INDISPONIBLE`), séparé du pool des sessions qu'il ne peut donc pas affamer.
- Appels sortants (Billets, Catalogue, Paiements) : `commun.http.ClientService` par la gateway
  (`URL_GATEWAY`), jeton du client `services` (`URL_JETON`, `SERVICES_CLIENT_ID`,
  `SERVICES_CLIENT_SECRET`, valeur de `KEYCLOAK_SERVICES_SECRET` dans `.env`).
- Plafond : `LIMITE_BILLETS_PAR_SEANCE` (10 par défaut), lignes `EN_ATTENTE` et `CONFIRMEE`.
- Base injoignable : 503 `BASE_INDISPONIBLE` après `DELAI_BASE` secondes (5 par défaut).
- Événements : `ticketing.order.confirmed` et `ticketing.order.expired` par l'outbox, relais
  actif si `RABBITMQ_URL` est défini.
- Carte de test : transmise à Paiements, jamais enregistrée ni journalisée.
- Migrations : `0001` (vide), `0002` (outbox, messages_traites), `0003` (commandes,
  lignes_commande), lancées une fois par le conteneur `commandes-migrations`.
- Contrat : `openapi.yaml`, vérifié par `pytest -m contract`.
