---
paths:
  - "services/*/src/**/infra/**"
  - "services/*/src/**/evenements/**"
  - "libs/commun/evenements.py"
  - "libs/commun/outbox.py"
  - "libs/commun/consommateurs.py"
---
# Événements

- Nom au passé : `ticketing.<entité>.<fait>` (`ticketing.order.confirmed`). Enveloppe
  `commun.evenements.Evenement` ; `data` versionnée par `version`.
- Publication : uniquement `publier_plus_tard(session, evenement)`, dans la même transaction
  que l'écriture métier. Jamais `broker.publish` depuis le code métier.
- Consommation : `@consommateur_idempotent(broker, sessions, nom=..., type_evenement=...)`. Le
  traitement écrit avec la session reçue : son effet et `messages_traites` vont ensemble.
- Un traitement en erreur lève une exception : trois tentatives, puis la file `<nom>.dlq`.
- Un consommateur ne suppose jamais l'ordre d'arrivée des messages.

```python
# Bon
async with session.begin():
    session.add(commande)
    await publier_plus_tard(session, Evenement.creer("ticketing.order.confirmed", {...}))

# Mauvais
await session.commit()
await broker.publish(commande, routing_key="order_confirmed")  # perdu si le broker tombe
```
