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
- Séance présente dans `seances_annulees` (vide en BIL-008) et aucun paiement enregistré : 409
  `SHOW_CANCELLED`, sans ligne.
- Carte de test `4000000000000002` refusée (paiement `REFUSE` enregistré), tout autre numéro de
  16 chiffres accepté ; le numéro n'est ni journalisé ni enregistré.
- Base injoignable : 503 `BASE_INDISPONIBLE` après `DELAI_BASE` secondes (5 par défaut).
- Migrations : `0001` (vide), `0002` (outbox, messages_traites, sans relais ni consommateur en
  BIL-008), `0003` (paiements, seances_annulees), lancées une fois par le conteneur
  `paiements-migrations`.
- Contrat : `openapi.yaml`, vérifié par `pytest -m contract`.
