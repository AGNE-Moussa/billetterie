---
paths:
  - "services/billets/**"
---
# Billets et QR code

- Aucun billet émis avant `ticketing.order.confirmed` : l'émission vit dans le consommateur
  idempotent de cet événement, jamais dans une route appelée par le client.
- Le QR code porte un identifiant de billet signé (HMAC, clé dans l'environnement), jamais des
  données lisibles et modifiables (nom, place, prix).
- La vérification du QR recalcule la signature ; un billet annulé ou déjà scanné est refusé.
- Un même événement reçu deux fois n'émet qu'un billet (idempotence, `messages_traites`).

```python
# Bon
@consommateur_idempotent(
    broker, sessions, nom="billets.order-confirmed", type_evenement="ticketing.order.confirmed"
)
async def emettre(session: AsyncSession, evenement: Evenement) -> None: ...


contenu_qr = f"{billet.id}.{signer(billet.id)}"

# Mauvais
contenu_qr = json.dumps({"nom": client.nom, "place": "A12"})  # falsifiable
```
