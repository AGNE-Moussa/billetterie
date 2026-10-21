---
paths:
  - "services/**/*.py"
  - "libs/**/*.py"
  - "infra/**/*.py"
---
# Python des services

- Typage strict (mypy) sur tout paramètre et tout retour ; tout est asynchrone (SQLAlchemy et
  httpx async), jamais d'appel bloquant (`requests`, `time.sleep`) dans une route.
- Appel vers un autre service : uniquement `commun.http.ClientService` (timeout, nouvelles
  tentatives, disjoncteur, jeton de service, corrélation). Jamais `httpx.AsyncClient` direct.
- Erreur métier : sous-classe de `commun.erreurs.ErreurMetier` avec un code stable ; elle sort
  en Problem Details. Jamais de `HTTPException` ni de trace renvoyée au client.
- Couches : `api/` (routes), `domaine/` (règles, sans SQLAlchemy), `infra/` (base) ;
  configuration par `pydantic-settings`, variables d'environnement uniquement.

```python
# Bon
class SeanceComplete(ErreurMetier):
    def __init__(self, seance: UUID) -> None:
        super().__init__("SEANCE_COMPLETE", 409, f"La séance {seance} est complète.")


reponse = await catalogue.get(f"/api/v1/seances/{seance}")  # ClientService

# Mauvais
raise HTTPException(409, "complet")
reponse = httpx.get(f"http://catalogue:8000/seances/{seance}")
```
