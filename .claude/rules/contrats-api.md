---
paths:
  - "**/openapi.yaml"
  - "docs/contrats/*.yaml"
  - "services/*/src/**/api/**"
---
# Contrats d'API

- Contrat d'abord : `services/<nom>/openapi.yaml` (OpenAPI 3.1) est la référence. Le test
  `pytest -m contract` compare le schéma généré par FastAPI au contrat.
- Routes : `/api/v1/<ressource>` au pluriel, verbes standards ; pagination `?page=&size=` (1 et
  20, `size` ≤ 100, sinon 422) en `Page[T]` sous-classée, `{elements, page, size, total}`.
- Chaque route déclare son `operation_id` (camelCase) et ses erreurs ; route protégée :
  `REPONSES_AUTH` ou `REPONSE_NON_AUTHENTIFIE` ; ressource d'un autre appelant : 404, jamais 403.
- Erreurs : Problem Details (`reponse_probleme(...)`) avec un code stable en MAJUSCULES, métier
  en anglais (`SEAT_ALREADY_TAKEN`), technique de commun en français (`REQUETE_INVALIDE`).
- Centimes (entiers), UUID, dates ISO 8601 avec fuseau, énumérations MAJUSCULES sans accent.

```python
# Bon
@routeur.post(
    "",
    operation_id="creerCommande",
    status_code=201,
    responses={**REPONSES_AUTH, 409: reponse_probleme("Place déjà prise (SEAT_ALREADY_TAKEN).")},
)

# Mauvais
@router.post("/createOrder")  # verbe dans l'URL, pas de version, erreurs non déclarées
```
