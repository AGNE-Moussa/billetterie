# Service commandes

Service sur le modèle de `services/echo/` (voir son README pour les conventions). BIL-008 :
passer commande et payer ; BIL-010 : expirer les commandes non payées.

- Préfixe de routes annoncé à Consul et Traefik : `/api/v1/orders`, sur l'hôte standard
  (`standard@file`) et sur l'hôte des revendeurs `HOTE_PARTENAIRES` (`partenaires@file`, quota
  par jeton, BIL-012).
- Revendeurs (BIL-012) : mêmes routes, rôle `partner` (Client Credentials), filtrées par le
  sujet du jeton comme pour un client. Colonne `canal` (migration 0005) : `PARTENAIRE` dès que
  le jeton porte `partner`, `DIRECT` sinon ; en base seulement, jamais dans l'API ni dans les
  événements. Documentation publiée : `docs/contrats/partenaires.yaml`.
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
  paiements `ACCEPTE` des commandes `EXPIREE` (ticket pas encore créé). La tâche d'expiration
  de BIL-010 ne peut pas la provoquer : elle relit `expire_le` sous `FOR UPDATE`, et
  `payerCommande` repousse `expire_le` (reverrouillage en confirmation) avant son `POST` ; une
  commande en cours de paiement n'est donc jamais expirée par la tâche. Seules les requêtes de
  BIL-008 restent concernées.
- Verrous prolongés sur une commande déjà expirée (review BIL-010, point 1) : `payerCommande`
  lit la commande `EN_ATTENTE` sans verrou, puis la tâche peut l'expirer avant que le
  reverrouillage en confirmation prolonge ses verrous à 1 h (Billets ne prolonge que les verrous
  encore détenus par la commande, sans jamais en créer). Si ce reverrouillage a abouti pour
  toutes les places et que la relecture sous `FOR UPDATE` trouve la commande `EXPIREE`,
  Commandes republie `ticketing.order.expired` dans cette transaction (mêmes données, sans
  `remboursement_du`, aucun paiement n'étant lu) et rend 409 `ORDER_NOT_PENDING` sans appel à
  Paiements. Billets libère alors les verrous qu'elle détient (comparer puis supprimer,
  consommateur idempotent), même si le premier événement a déjà été traité ou a fini en file
  d'erreur ; un verrou repris entre-temps par une autre commande n'est jamais touché.
- Tâche d'expiration (BIL-010) : toutes les `EXPIRATION_PERIODE` secondes (30 par défaut, le
  premier cycle une période après le démarrage), l'instance qui obtient le verrou Redis
  `commandes:tache:expiration` (`SET NX PX`, valeur = `INSTANCE`, durée = une période, jamais
  relâché) expire au plus `EXPIRATION_LOT` commandes (100 par défaut) `EN_ATTENTE` dont
  `expire_le <= maintenant`, par `expire_le` croissant. Chaque commande est relue sous
  `FOR UPDATE` (statut et `expire_le`) puis expirée comme à BIL-008 (lecture de Paiements si
  `paiement_demande`, `remboursement_du`) ; Paiements injoignable : commande laissée
  `EN_ATTENTE`, reprise au cycle suivant. Redis injoignable : cycle sauté (`WARNING`).
  `REDIS_URL` est obligatoire ; la connexion n'est ouverte qu'au premier cycle.
- **Limite connue, hors périmètre de BIL-010** : une commande `EN_ATTENTE` dont `expire_le`
  est NULL (réservation de `creerCommande` interrompue par un arrêt de l'instance avant la
  réponse du premier verrou) n'a pas d'échéance : la tâche ne la voit jamais et elle reste
  `EN_ATTENTE`. Ses éventuels verrous de place expirent seuls dans Redis ; elle compte encore
  dans le plafond de billets du client. À traiter dans un ticket dédié.
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
  lignes_commande), `0004` (index `ix_commandes_statut_expire_le`), lancées une fois par le
  conteneur `commandes-migrations`.
- Contrat : `openapi.yaml`, vérifié par `pytest -m contract`.
