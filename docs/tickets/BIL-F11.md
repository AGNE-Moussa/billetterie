# BIL-F11 : Code commun : Problem Details et corrélation

- **Branche** : `feat/bil-f11-erreurs-correlation`
- **Dépend de** : BIL-F08

## Objectif

Fournir dans `libs/commun` le format d'erreur Problem Details et la propagation de l'identifiant
de corrélation.

## Étapes

- [x] 1. `libs/commun/erreurs.py` : exception `ErreurMetier(code, statut, détail)` et
  gestionnaires FastAPI qui produisent `application/problem+json` avec `type`, `title`, `status`,
  `detail`, `code`, `correlation_id`
- [x] 2. Erreurs de validation Pydantic converties au même format (422)
- [x] 3. `libs/commun/correlation.py` : middleware qui lit ou crée `X-Correlation-Id`, le stocke
  dans un `ContextVar` et l'ajoute aux journaux JSON
- [x] 4. Brancher les deux sur `services/echo`
- [x] 5. Tests unitaires du format (`tests/unit/test_erreurs.py`, `tests/unit/test_correlation.py`)

## Critères d'acceptance

- [x] CA1 : une erreur métier renvoie un corps conforme à la RFC 9457 avec un code stable
- [x] CA2 : chaque ligne de journal contient l'identifiant de corrélation de la requête (journaux
  applicatifs et journal d'accès d'uvicorn, vérifié avec des requêtes simultanées)

## Contraintes

- Jamais de trace d'exception renvoyée au client : 500 générique `ERREUR_INTERNE`, trace dans les
  journaux seulement (testé).

## Décisions (validées par le développeur)

- Les exceptions du domaine héritent d'`ErreurMetier` (code et statut portés par l'exception).
- Journaux JSON avec un formatter maison (bibliothèque standard, sans dépendance).

## Hors ticket, corrigé au passage

- Le plugin Traefik `correlation` posait l'en-tête sur la réponse avant d'appeler le service :
  maintenant que le service le renvoie aussi, la réponse portait deux `X-Correlation-Id`. Le
  plugin ne le pose plus que si le service ne l'a pas fait (vérifié sur la plateforme locale).
