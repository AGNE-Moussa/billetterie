# BIL-F13 : Code commun : scopes et autorisation dans FastAPI

- **Branche** : `feat/bil-f13-autorisation`
- **Dépend de** : BIL-F10, BIL-F11

## Objectif

Permettre à chaque route de déclarer en une ligne les scopes et rôles qu'elle exige.

## Étapes

- [x] 1. `libs/commun/auth.py` : modèle `Appelant` (identifiant, rôles, scopes, client) avec
  revérification de la signature du jeton ; `X-User-Id` du vérificateur doit correspondre au jeton
- [x] 2. Dépendances `exige_scopes("orders:write")` et `exige_role("admin")` qui lèvent un Problem
  Details 403 (`SCOPE_MANQUANT`, `ROLE_MANQUANT`)
- [x] 3. Utilitaire de test `libs/commun/faux_jetons.py` (`EmetteurDeTest`) qui fabrique un jeton
  signé par une clé de test et sert le JWKS correspondant
- [x] 4. Exemple sur `services/echo` : POST exige le scope `echos:write`, GET un appelant
  authentifié

## Critères d'acceptance

- [x] CA1 : un jeton sans le scope requis reçoit 403 au format Problem Details (tests unitaires ;
  plateforme locale : `client.test` reçoit 403 `SCOPE_MANQUANT` sur le POST d'echo)
- [x] CA2 : les tests peuvent simuler n'importe quel appelant sans Keycloak (`EmetteurDeTest`, ou
  remplacement de la dépendance `appelant`)

## Contraintes

- Le service ne fait jamais confiance à des en-têtes seuls : la signature du jeton est vérifiée
  (testé ; plateforme locale : un appel direct au conteneur avec `X-User-Id: admin` reçoit 401).

## Décisions (validées par le développeur)

- La validation des JWT passe du vérificateur à `libs/commun/jetons.py`, partagée par le
  vérificateur et les services.
- Exemple echo : scope `echos:write`, donné par défaut au seul client `services`.
- Déclarer `clientScopes` dans le realm remplace les scopes intégrés de Keycloak (vérifié : sans
  eux, les jetons perdent `realm_access`). Ils sont donc tous listés dans le realm (export de
  Keycloak 26.4.1, sans les scopes SAML), suivis des scopes métier.

## Mise à jour d'une plateforme déjà démarrée

Le realm n'est importé que s'il n'existe pas : `make reset`, ou créer le client scope
`echos:write` et l'ajouter aux scopes par défaut du client `services` dans la console Keycloak.
