# Plan de test : BIL-F26, Front : squelette React et outillage

- Ticket : `docs/tickets/BIL-F26.md` ; contrat : aucun (le squelette n'appelle aucune API)
- Niveaux : composant, parcours

Périmètre : le ticket a trois critères (CA1 à CA3) et une contrainte (accessibilité par
eslint-plugin-jsx-a11y). CA1 et CA3 portent sur l'outillage : ils se vérifient par des
commandes, pas par des cas inventés. Les étapes 3 à 6 n'ont pas de critère propre ; elles sont
reprises ci-dessous en critères dérivés E3 à E6, validés (Q6).

Le ticket ne touche ni Billets ni Commandes : aucun cas de concurrence obligatoire.

Outillage attendu : niveau `composant` avec Vitest, Testing Library et jsdom, rendu sous
`MemoryRouter` et un `QueryClientProvider` de test ; aucune API simulée (pas de MSW utile ici,
aucun appel d'API). Niveau `parcours` avec Playwright, `baseURL` `http://localhost`, contre la
plateforme démarrée par `make up` (front servi par Nginx derrière Traefik). Dans Vitest et
Playwright, le nom du cas sert de libellé du `it(...)` / `test(...)`.

Commandes (PowerShell, depuis `frontend/` sauf mention) : `curl.exe` plutôt que l'alias `curl`.

## Questions

Réponses du développeur (validation 1) :

1. Page d'accueil : un titre de niveau 1 « Billetterie » dans un `main`, trouvé par
   `getByRole('heading', { level: 1, name: 'Billetterie' })`.
2. URL profonde : `/page-inexistante`. On vérifie aussi que `/` rechargée fonctionne.
3. Route inconnue côté React Router : page « Page introuvable » (titre de niveau 1) avec un lien
   vers l'accueil. Statut HTTP 200 (repli SPA de Nginx).
4. États d'écran : seul l'état succès est testé dans ce ticket ; chargement, vide et erreur
   arrivent avec le premier écran qui lit des données.
5. `Cache-Control` : `/assets/*` → `public, max-age=31536000, immutable` ; `index.html` et le
   repli SPA → `no-cache`.
6. Critères dérivés E3 à E6 validés.
7. `npm run dev` : `GET /` à 200 sur le port 5173, fixé dans `vite.config.ts` (`strictPort`).
8. Playwright : en local seulement, contre `make up`, Chromium seul ; la CI lance
   `npx playwright test --list` pour vérifier qu'ils compilent.
9. Image du front : ajoutée à la matrice `images` existante (amd64 et arm64, sans publication,
   contexte `frontend/`) ; `--if-present` retiré du job `frontend`.
10. GitHub Pages abandonné : Nginx seul, base Vite `/` ; les mentions de GitHub Pages sont
    retirées (`README.md`, `.env.example`, `frontend/CLAUDE.md`).

Plus aucune question ouverte : plan validé.

## CA1 : `npm run dev`, `npm test` et `npm run build` passent

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_la_page_d_accueil_s_affiche` | composant | rendu de la page d'accueil seule, sous `MemoryRouter` et `QueryClientProvider` de test | le titre h1 « Billetterie » est trouvé par son rôle accessible (`getByRole`), aucune erreur en console |

Vérification par commandes (non automatisée en cas de test) :

| Commande | Attendu |
|---|---|
| `npm ci` | installation sans erreur, `package-lock.json` inchangé |
| `npm run dev`, puis `curl.exe -s -o NUL -w "%{http_code}" http://localhost:5173/` | serveur Vite démarré, 200 |
| `npm test -- --run` | Vitest s'exécute, code de sortie 0 une fois l'implémentation faite |
| `npm run build` | code de sortie 0, `dist/index.html` et `dist/assets/*` produits, TypeScript strict sans erreur |
| `npm run lint` | Prettier et ESLint sans erreur |

## CA2 : `docker compose up` puis `http://localhost/` affiche la page d'accueil via Traefik, et une URL profonde rechargée ne renvoie pas de 404

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_la_route_racine_affiche_la_page_d_accueil` | composant | routeur de l'application sous `MemoryRouter`, `initialEntries=["/"]` | la page d'accueil est rendue (titre h1 « Billetterie ») |
| `test_une_route_inconnue_affiche_la_page_introuvable` | composant | routeur de l'application, `initialEntries` = `/page-inexistante` | titre h1 « Page introuvable » et lien vers l'accueil, aucune exception |
| `test_l_accueil_s_affiche_via_traefik_et_une_url_profonde_rechargee_ne_renvoie_pas_404` | parcours | plateforme démarrée (`make up`) ; `page.goto("/")`, puis `page.goto(/page-inexistante)` et `page.reload()` | `/` : réponse 200, `text/html`, page d'accueil visible ; URL profonde après rechargement : réponse 200 (pas 404), `text/html`, titre h1 « Page introuvable » |

Vérification complémentaire par commandes, plateforme démarrée :

| Commande | Attendu |
|---|---|
| `docker compose ps frontend` | service `frontend` à l'état `healthy` (ou `running` si aucun healthcheck n'est prévu) |
| `curl.exe -sI http://localhost/` | 200, `Content-Type: text/html` |
| `curl.exe -sI http://localhost//page-inexistante` | 200, `Content-Type: text/html` (repli `try_files` vers `index.html`) |

## CA3 : les tests produits par `unit-test-writer` (Vitest) et `integration-test-writer` (Playwright, `baseURL` `http://localhost`) s'exécutent et échouent sur une assertion, pas sur une erreur de compilation ou d'import

Critère d'outillage : vérifié par commandes, en phase rouge, sur les cas de ce plan.

| Commande | Attendu |
|---|---|
| `npm test -- --run` avec les cas `composant` de ce plan écrits avant l'implémentation | chaque échec est une `AssertionError` (ou « Unable to find an element ») ; aucun « Failed to resolve import », « Cannot find module », erreur de transformation ni « document is not defined » (jsdom configuré, matchers `@testing-library/jest-dom` chargés) |
| `npx playwright test --list` | les cas `parcours` sont découverts, sans erreur de compilation TypeScript |
| `npx playwright test`  avec les cas `parcours` en phase rouge | échecs sur `expect(...)`, pas sur la configuration ; la configuration lue a `use.baseURL` = `http://localhost` |
| `npx tsc --noEmit -p .` | aucune erreur de type dans les fichiers de test (types Vitest, Testing Library et Playwright résolus) |

## Contrainte : accessibilité vérifiée par eslint-plugin-jsx-a11y

| Commande | Attendu |
|---|---|
| `npx eslint --print-config src/main.tsx` | la configuration contient des règles `jsx-a11y/*` actives |
| `npm run lint` | passe sur le squelette |

Le cas `test_la_page_d_accueil_s_affiche` (CA1) cherche les éléments par rôle accessible, ce qui
vérifie aussi la présence de rôles et de noms accessibles.

## E3 : `VITE_API_URL` et `VITE_KEYCLOAK_URL`, par défaut `/api` et `/auth` (étape 3)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_sans_variable_les_urls_sont_les_chemins_relatifs_api_et_auth` (paramétré) | composant (module de configuration, sous Vitest) | `vi.stubEnv` : `VITE_API_URL` puis `VITE_KEYCLOAK_URL` non définies | URL de l'API = `/api` ; URL de Keycloak = `/auth` |
| `test_une_variable_definie_remplace_le_chemin_par_defaut` (paramétré) | composant (module de configuration, sous Vitest) | `VITE_API_URL` = `http://api.exemple.test/api`, `VITE_KEYCLOAK_URL` = `http://auth.exemple.test/auth` | chaque URL exposée vaut la variable fournie |

## E4 : image Nginx multi-étapes, repli SPA et cache long sur les fichiers versionnés (étape 4)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_les_fichiers_versionnes_ont_un_cache_long_et_l_accueil_non` | parcours | plateforme démarrée ; `request.get("/")`, extraction d'un `src` de script `/assets/*.js` de la page, puis `request.get(<ce fichier>)` | fichier versionné : 200, `Cache-Control` = `public, max-age=31536000, immutable` ; `index.html` : `Cache-Control` = `no-cache` |

Vérification par commandes :

| Commande | Attendu |
|---|---|
| `docker build -f frontend/Dockerfile -t billetterie-frontend:test frontend` | build réussi |
| `docker image inspect billetterie-frontend:test` | image finale Nginx, sans Node ni `node_modules` (étape de build séparée) |

## E5 : service `frontend` routé par Traefik sur `/`, priorité plus basse que `/api` et `/auth` (étape 5)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_api_et_auth_restent_servis_par_leurs_services_et_non_par_le_front` | parcours | plateforme démarrée ; `request.get("/api/v1/echos")` sans jeton, puis `request.get("/auth/realms/billetterie/.well-known/openid-configuration")` | `/api/v1/echos` : 401, `application/problem+json` (pas le `index.html` du front) ; `/auth/...` : 200, `application/json`, `issuer` = `http://localhost/auth/realms/billetterie` |

Vérification par commandes :

| Commande | Attendu |
|---|---|
| `curl.exe -sI http://localhost/api/v1/echos` | 401, `Content-Type: application/problem+json` |
| `curl.exe -sI http://localhost/auth/realms/billetterie/.well-known/openid-configuration` | 200, `Content-Type: application/json` |

## E6 : job de CI qui construit l'image du front à chaque PR (étape 6)

Vérifié par commande et par la PR elle-même, sans cas de test :

| Vérification | Attendu |
|---|---|
| `git diff main -- .github/workflows/ci.yml` | un job (ou une entrée de la matrice `images`) construit `frontend/Dockerfile` sans publication  ; `--if-present` retiré des étapes `test` et `build` du job `frontend` |
| checks GitHub de la PR BIL-F26 | le job de l'image front et le job `frontend` (`lint`, `test -- --run`, `build`) sont verts |

## Couverture

| Critère | Cas |
|---|---|
| CA1 | `test_la_page_d_accueil_s_affiche` ; commandes `npm ci`, `npm run dev`, `npm test -- --run`, `npm run build`, `npm run lint` |
| CA2 | `test_la_route_racine_affiche_la_page_d_accueil`, `test_une_route_inconnue_affiche_la_page_introuvable`, `test_l_accueil_s_affiche_via_traefik_et_une_url_profonde_rechargee_ne_renvoie_pas_404` |
| CA3 | aucun cas propre : commandes en phase rouge (`npm test -- --run`, `npx playwright test --list`, `npx playwright test`, `npx tsc --noEmit`) |
| Contrainte a11y | commandes `eslint --print-config`, `npm run lint` ; `test_la_page_d_accueil_s_affiche` |
| E3 | `test_sans_variable_les_urls_sont_les_chemins_relatifs_api_et_auth`, `test_une_variable_definie_remplace_le_chemin_par_defaut` |
| E4 | `test_les_fichiers_versionnes_ont_un_cache_long_et_l_accueil_non` ; commandes `docker build`, `docker image inspect` |
| E5 | `test_api_et_auth_restent_servis_par_leurs_services_et_non_par_le_front` ; commandes `curl.exe` |
| E6 | aucun cas : diff de `ci.yml` et checks de la PR |
