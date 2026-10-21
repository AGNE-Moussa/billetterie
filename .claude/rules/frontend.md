---
paths:
  - "frontend/**"
---
# Front-end

- TypeScript strict, React fonctionnel, React Router, TanStack Query pour les données serveur.
- Appels d'API : uniquement le client typé généré depuis les contrats (`openapi-typescript`).
  Jamais de `fetch` écrit à la main vers une URL d'API.
- Jeton d'accès gardé en mémoire (oidc-client-ts) ; jamais dans `localStorage` ni dans un
  cookie lisible en JavaScript.
- Erreur d'API : afficher le `title` et le `detail` du Problem Details ; décider sur `code`.
- Chaque écran gère quatre états : chargement, vide, erreur, succès.
- Accessibilité : libellés de formulaire, rôles ARIA, navigation au clavier.

```tsx
// Bon
const { data, error, isPending } = useQuery({
  queryKey: ["seances", id],
  queryFn: () => api.lireSeance(id),
});
if (error) return <Erreur probleme={error} />;

// Mauvais
localStorage.setItem("token", jeton);
fetch("/api/v1/seances/" + id).then((r) => r.json());
```
