---
paths:
  - "**/openapi.yaml"
  - "services/*/src/**/api/**"
---
# Contrats d'API

- Contrat d'abord : `services/<nom>/openapi.yaml` (OpenAPI 3.1) est la référence. Le test
  `pytest -m contract` compare le schéma généré par FastAPI au contrat.
- Routes : `/api/v1/<ressource>` au pluriel, verbes HTTP standards, pagination `?page=&size=`.
- Chaque route déclare un `operation_id` en camelCase et ses réponses d'erreur.
- Erreurs : Problem Details `application/problem+json` (`reponse_probleme(...)`) avec un code
  métier stable en MAJUSCULES (`SEAT_ALREADY_TAKEN`), jamais un message seul.
- Route protégée : `REPONSE_NON_AUTHENTIFIE` ou `REPONSES_AUTH` (401, 403) dans `responses`.
- Montants en centimes (entiers), identifiants en UUID, dates en ISO 8601 avec fuseau.

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
