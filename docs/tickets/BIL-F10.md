# BIL-F10 : Vérificateur de jetons ForwardAuth

- **Branche** : `feat/bil-f10-forwardauth`
- **Dépend de** : BIL-F07, BIL-F09

## Objectif

Écrire un petit service FastAPI appelé par Traefik (ForwardAuth) qui valide chaque JWT avant le
routage.

## Étapes

- [x] 1. `infra/verificateur/` : service FastAPI qui lit l'en-tête `Authorization`, valide
  signature, expiration, émetteur et audience avec les clés JWKS du realm (cache avec
  rafraîchissement)
- [x] 2. Réponse 200 avec les en-têtes `X-User-Id`, `X-User-Roles`, `X-Client-Id` ; 401 sinon
- [x] 3. Liste de routes publiques configurable par variable (`ROUTES_PUBLIQUES`)
- [x] 4. Middleware ForwardAuth branché sur les routes protégées dans Traefik
- [x] 5. Tests : jeton valide, expiré, mauvaise signature, mauvais émetteur

## Critères d'acceptance

- [x] CA1 : sans jeton, une route protégée répond 401 sans atteindre le service
- [x] CA2 : avec un jeton valide, le service reçoit `X-User-Id`
- [x] CA3 : un jeton expiré est refusé

## Contraintes

- Aucun appel à Keycloak par requête : validation locale avec les clés en cache.

## Décisions (validées par le développeur)

- Audience : mapper `billetterie-api` ajouté aux clients `frontend` et `services` du realm ; le
  vérificateur exige cette audience.
- Protégé par défaut : la vérification entre dans les chaînes `standard` et `partenaires` ;
  Keycloak passe sur une chaîne `public`.
- Routes publiques au format `MÉTHODE /préfixe`, séparées par des virgules, correspondance par
  segment ; un jeton fourni sur une route publique est quand même vérifié.

## Vérifications

- Tests unitaires du vérificateur (`infra/verificateur/tests/unit`, 25 tests) : jeton valide,
  expiré (CA3), mauvaise signature, mauvais émetteur, mauvaise audience, clé inconnue, HS256,
  routes publiques, cache et rotation des clés, Keycloak indisponible.
- Bout en bout (`tests/integration/test_verification_jeton.py`) : 401 sans jeton sans atteindre
  le service (CA1), `X-User-Id` reçu par le service (CA2), faux `X-User-Id` retiré, preflight
  CORS sans jeton.
- Plateforme locale : `/api/v1/echos` répond 401 sans jeton et passe avec un jeton du client
  `services`.

## Mise à jour d'une plateforme déjà démarrée

Le realm n'est importé que s'il n'existe pas : ajouter le mapper d'audience exige `make reset`
(ou l'ajout du mapper dans la console Keycloak). Traefik doit être redémarré
(`docker compose restart traefik`) pour relire `dynamique.yml`, et Consul rechargé
(`docker compose exec consul consul reload`) pour `infra/consul/keycloak.json`.
