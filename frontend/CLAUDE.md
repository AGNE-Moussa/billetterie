# Front-end

Application React : Vite, TypeScript strict, React Router, TanStack Query. Le squelette est
construit dans BIL-F26 à BIL-F28 ; tant qu'il n'existe pas, ces commandes ne fonctionnent pas.

## Commandes

```sh
npm install        # installer les dépendances
npm run dev        # serveur de développement Vite
npm run build      # build de production (dist/, servi par Nginx derrière Traefik)
npm run test       # Vitest et Testing Library
npm run lint       # ESLint et Prettier
npx playwright test  # parcours de bout en bout
```

## Conventions

- Client d'API typé généré depuis les contrats OpenAPI (openapi-typescript), jamais écrit à la main.
- Erreurs d'API au format Problem Details, affichées proprement.
- Authentification Keycloak en Authorization Code + PKCE (oidc-client-ts) ; jeton gardé en
  mémoire, jamais dans localStorage.
- Chaque écran gère les états chargement, vide et erreur, et reste accessible.
- Règles détaillées : `.claude/rules/frontend.md` (BIL-F18).
