---
paths:
  - "**/tests/**"
  - "frontend/**/*.test.tsx"
  - "frontend/e2e/**"
---
# Tests

- pytest, avec anyio pour l'asynchrone (`pytestmark = pytest.mark.anyio`).
- Nommage : `test_<comportement attendu>`, en français, lisible comme une phrase.
- Unitaire (`tests/unit/`, `services/*/tests/unit/`) : sans Docker, dépôt en mémoire, jetons de
  `commun.faux_jetons.EmetteurDeTest`.
- Intégration : vraie base, vrai Redis, vrai RabbitMQ via Testcontainers. Jamais de simulacre
  de la base (pas de `MagicMock` pour une session SQLAlchemy).
- Un test vérifie le comportement observable (statut, corps, ligne en base), pas le code.
- Données synthétiques uniquement ; secrets générés (`secrets.token_urlsafe`).
- Un test rouge doit l'être pour la bonne raison : comportement absent, pas erreur d'import.

```python
# Bon
async def test_une_place_deja_prise_renvoie_409(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/reservations", json={"place": "A12"})
    reponse = await client.post("/api/v1/reservations", json={"place": "A12"})
    assert reponse.json()["code"] == "SEAT_ALREADY_TAKEN"


# Mauvais
def test_reservation(mocker):
    mocker.patch("billets.infra.depot.Session.execute")  # simulacre de la base
```
