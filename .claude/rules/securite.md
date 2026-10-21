# Sécurité

- Aucun secret dans le dépôt, même d'exemple réaliste : valeurs dans `.env` (jamais commité),
  `.env.example` avec des valeurs vides.
- Route protégée : `AppelantDep`, `exige_scopes(...)` ou `exige_role(...)` (commun.auth). Le
  service revérifie toujours le jeton ; il ne croit jamais un en-tête `X-User-*` seul.
- Scopes : `events:read`, `events:write`, `orders:read`, `orders:write`, `tickets:read`.
  Rôles : `customer`, `partner`, `admin`.
- Un revendeur ne voit que ses propres commandes : filtrer par l'appelant, jamais par un
  paramètre fourni par le client.
- Données de test synthétiques uniquement (`client.test@exemple.test`).
- Journaux : jamais de jeton, de mot de passe ni de donnée de carte.

```python
# Bon
commandes = await depot.commandes_de(appelant.client)

# Mauvais
commandes = await depot.commandes_de(requete.query_params["revendeur"])
```
