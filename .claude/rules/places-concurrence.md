---
paths:
  - "services/billets/**"
  - "services/commandes/**"
---
# Places et concurrence

Règle centrale du projet : une place n'est jamais vendue deux fois, même sous une charge extrême.

- Verrou d'une place : Redis `SET <clé> <propriétaire> NX PX <durée>`, avec expiration
  (10 min par défaut), libéré seulement par son propriétaire.
- Contrainte unique en base toujours présente (`uq_billets_place` sur séance et place) : le
  verrou Redis évite la plupart des conflits, la base garantit le reste.
- Jamais de « lire puis écrire » sans verrou : la place peut être prise entre les deux.
- Conflit : `ErreurMetier("SEAT_ALREADY_TAKEN", 409, ...)`, jamais une erreur 500.
- Tout test de ces services inclut un cas de concurrence (plusieurs clients, même place).

```python
# Bon
pris = await redis.set(f"place:{seance}:{place}", commande, nx=True, px=DUREE_VERROU_MS)
if not pris:
    raise PlaceDejaPrise(place)

# Mauvais
if not await depot.est_reservee(place):  # lire...
    await depot.reserver(place)  # ...puis écrire : deux clients passent
```
