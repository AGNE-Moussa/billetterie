# BIL-F26 : Front : squelette React et outillage

- **Branche** : `feat/bil-f26-front-squelette`
- **Dépend de** : BIL-F04, BIL-F07
- **Service** : frontend

## Objectif

Créer l'application React du projet dans `frontend/`, avec son outillage de qualité et son image
Nginx servie par Traefik.

## Étapes

- [x] 1. Vite + React + TypeScript strict ; ESLint, Prettier ; React Router ; TanStack Query.
- [x] 2. Vitest et Testing Library ; Playwright installé avec un premier test qui ouvre la page
  d'accueil.
- [x] 3. Variables `VITE_API_URL` et `VITE_KEYCLOAK_URL` ; par défaut des chemins relatifs
  (`/api`, `/auth`), puisque front et API partagent le même domaine.
- [x] 4. `frontend/Dockerfile` multi-étapes : build Node, puis image Nginx qui sert `dist/` avec
  repli SPA (`try_files`) et cache long sur les fichiers versionnés.
- [x] 5. Service `frontend` dans `compose.yaml`, routé par Traefik sur `/` (priorité plus basse
  que `/api` et `/auth`).
- [x] 6. Job de CI qui construit l'image du front à chaque PR.

Note (BIL-F19) : `frontend/` contient déjà `package.json` (Prettier 3.9.9, ESLint 10.11.0,
@eslint/js 10.0.1, typescript-eslint 8.71.1, TypeScript 6.0.3, versions épinglées),
`eslint.config.js`, `.prettierrc.json` et `.prettierignore` : partir de ces fichiers, y ajouter
Vite, React, Vitest et les scripts `dev`, `test` et `build`. Le hook `formater.py` utilise
`frontend/node_modules/.bin/prettier` et `eslint` ; `tests_rapides.py` lance
`npm run test -- --run`. Le job CI `frontend` lance `test` et `build` avec `--if-present` : le
retirer une fois ces scripts créés.

## Critères d'acceptance

- [x] CA1 : `npm run dev`, `npm test` et `npm run build` passent
- [x] CA2 : `docker compose up` puis `http://localhost/` affiche la page d'accueil via Traefik, et
  une URL profonde rechargée ne renvoie pas de 404
- [x] CA3 : les tests produits par `unit-test-writer` (Vitest) et `integration-test-writer`
  (Playwright, `baseURL` `http://localhost`) s'exécutent et échouent sur une assertion, pas sur
  une erreur de compilation ou d'import

## Contraintes

- Aucune bibliothèque de composants lourde imposée ; accessibilité vérifiée par
  eslint-plugin-jsx-a11y.

## Décisions (validation 1)

- Accueil : titre h1 « Billetterie » dans un `main` ; route inconnue (`/page-inexistante`) :
  page « Page introuvable » (h1) avec un lien vers l'accueil, statut 200 par le repli SPA.
- Seul l'état succès est testé ; les autres états arrivent avec le premier écran à données.
- `Cache-Control` : `/assets/*` en `public, max-age=31536000, immutable`, `index.html` et le
  repli en `no-cache`.
- Critères dérivés E3 à E6 du plan validés ; `npm run dev` prouvé par `GET /` à 200 sur le
  port 5173 (`strictPort`).
- Playwright en local contre `make up`, Chromium seul ; la CI liste les tests
  (`npx playwright test --list`).
- Image du front dans la matrice `images` de la CI (contexte `frontend/`) ; `--if-present`
  retiré du job `frontend`.
- GitHub Pages abandonné : Nginx seul, base Vite `/` ; mentions retirées de `README.md`,
  `.env.example` et `frontend/CLAUDE.md`.
- Workflow : la liste d'écriture d'`implementer` couvre désormais la configuration du front
  (`frontend/*.ts`, `*.js`, `*.json`, `index.html`, `Dockerfile`, `nginx.conf`, `public/`),
  `.env.example` et `README.md`.
- jsx-a11y : on garde ESLint 10 avec un `overrides` npm (le plugin ne déclare qu'ESLint 9) ;
  vérifié : `jsx-a11y/alt-text` refuse une image sans `alt`. À retirer quand le plugin déclarera
  ESLint 10.
- Sorties de Playwright ignorées par `.gitignore` et `frontend/.prettierignore`.

## Décisions (validation 2)

- Routeur du front limité : `PathPrefix(/)` sauf `/api` et `/auth`, pour qu'un service sans
  instance saine ne soit jamais servi par le front.
- `passWithNoTests` retiré de Vitest.
- Nginx sans root (image non privilégiée) ; chaîne de middlewares `public@file`, comme Keycloak ;
  script `typecheck` gardé ; images `node:22.20.0-alpine` et `nginx` épinglées.
- Workflow : `frontend/playwright.config.ts` verrouillé à partir de l'implémentation
  (`proteger_fichiers`, `git_sur`).
