# BIL-F12 : Code commun : client HTTP résilient

- **Branche** : `feat/bil-f12-client-http`
- **Dépend de** : BIL-F11

## Objectif

Écrire le seul client HTTP autorisé entre services : timeout, nouvelles tentatives sur les
opérations idempotentes et disjoncteur.

## Étapes

- [x] 1. `libs/commun/http.py` : classe `ClientService` basée sur `httpx.AsyncClient`, timeout par
  défaut de 2 s
- [x] 2. Nouvelles tentatives (3 au maximum) uniquement sur GET ou sur requête portant une clé
  d'idempotence (`Idempotency-Key`), backoff exponentiel avec gigue (tenacity)
- [x] 3. Disjoncteur par service cible : ouvert après 5 échecs, demi-ouvert après 30 s ; état
  exposé dans la jauge Prometheus `client_http_disjoncteur_etat{cible}`
- [x] 4. Propagation automatique de `X-Correlation-Id` et du jeton de service (`JetonService`,
  Client Credentials, mis en cache jusqu'à expiration moins 30 s)
- [x] 5. Erreur `ServiceIndisponible` convertie en Problem Details 503 (`SERVICE_INDISPONIBLE`)
- [x] 6. Tests unitaires avec un faux transport httpx (`tests/unit/test_client_http.py`)

## Critères d'acceptance

- [x] CA1 : un POST sans clé d'idempotence n'est jamais rejoué (503, timeout, connexion refusée)
- [x] CA2 : après 5 échecs, les appels échouent immédiatement sans réseau
- [x] CA3 : le disjoncteur se referme après un appel réussi en demi-ouvert

## Contraintes

- Typage strict ; aucune dépendance à un framework de résilience lourd (tenacity pour les
  tentatives, disjoncteur maison, comme prévu par l'ADR-001).

## Décisions (validées par le développeur)

- Métrique publiée dès maintenant avec `prometheus-client` ; BIL-F15 exposera `/metrics`.
- Chaque tentative échouée compte pour le disjoncteur (réseau, timeout, 500, 502, 503, 504) ;
  les 4xx ne comptent pas et sont rendues telles quelles.
- En-tête de la clé d'idempotence : `Idempotency-Key`.

## Choix techniques

- Les autres services sont joints par la gateway (`base_url`), conformément à l'ADR-001 : aucun
  code de découverte dans les services.
- En demi-ouvert, un seul appel d'essai passe à la fois ; les autres échouent sans réseau.
