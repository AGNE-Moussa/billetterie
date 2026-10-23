# Review : BIL-F26, Front : squelette React et outillage

- Diff relu : `git diff` (16 fichiers suivis modifiés) et fichiers non suivis de `git status`
  (`frontend/src/`, `frontend/e2e/`, `Dockerfile`, `nginx.conf`, `.dockerignore`, `index.html`,
  `vite.config.ts`, `playwright.config.ts`, `tsconfig*.json`, `infra/consul/frontend.json`,
  ticket et plan de test), soit 30 fichiers ; rien n'est commité, `git diff main...HEAD` est vide.
- Seconde review, après les décisions de la validation 2 (`docs/tickets/BIL-F26.md:70-78`).
- Verdict : 0 bloquant, 0 à corriger, 0 suggestion ouverte (3 points corrigés, 1 corrigé en
  partie par décision, 4 suggestions non retenues)

Résultats mesurés par l'orchestrateur, non rejoués ici (relecture seule) : Vitest 7/7,
Playwright 3/3, lint et typecheck du front OK, conteneur en `uid=101(nginx)`, echo arrêté :
`GET /api/v1/echos` répond 404 `text/plain` (plus de repli vers le front), echo relancé : 401 ;
`make lint` et `make typecheck` OK, `make test-unit` 397 passed.

## Points de la première review

| # | Classement initial | Fichier:ligne | Constat initial | Statut |
|---|---|---|---|---|
| 1 | à corriger | `infra/consul/frontend.json:9` | `PathPrefix(`/`)` captait `/api` et `/auth` quand le service n'avait plus d'instance saine (panne d'API servie en 200 HTML). | **Corrigé** : ``PathPrefix(`/`) && !PathPrefix(`/api`) && !PathPrefix(`/auth`)``, priorité 1 gardée (ligne 10). Mesuré : 404 `text/plain` echo arrêté. Commentaires alignés (`compose.yaml:278`, `frontend/nginx.conf:1`). |
| 2 | à corriger | `frontend/vite.config.ts:12-17` | `passWithNoTests: true` laissait passer zéro test trouvé. | **Corrigé** : option retirée, le bloc `test` ne garde que `environment`, `globals`, `setupFiles`, `include`. |
| 3 | à corriger | `frontend/package.json:15-19` | Override `eslint-plugin-jsx-a11y` → ESLint 10 non documenté. | **Validé et documenté** par le développeur : `docs/tickets/BIL-F26.md:65-67` (raison, vérification `jsx-a11y/alt-text`, condition de retrait). |
| 4 | suggestion | `.claude/agents/implementer.md:10` | La liste d'écriture d'`implementer` couvre les fichiers de configuration des tests. | **Corrigé en partie, par décision** : `frontend/playwright.config.ts` verrouillé dès l'implémentation (`.claude/hooks/proteger_fichiers.py:27-30,55-59`, `.claude/hooks/git_sur.py:78-79`), testé (`tests/unit/test_hooks.py:79-92`, squelette et tests libres, implémentation et review verrouillées, outil d'écriture et shell). Le bloc `test` de `frontend/vite.config.ts` reste modifiable par `implementer` : la review le contrôle à chaque ticket front. |
| 5 | suggestion | `frontend/Dockerfile:18-23` | Nginx en root ; healthcheck hors de l'image. | **Corrigé pour le root** : `nginxinc/nginx-unprivileged:1.28.0-alpine`, `EXPOSE 8080`, `listen 8080` (`frontend/nginx.conf:4`), port reporté dans `infra/consul/frontend.json:6,17` et `compose.yaml:286`. Mesuré : `uid=101(nginx)`. **Healthcheck dans l'image : non retenu** (reste dans `compose.yaml:285-289`). |
| 6 | suggestion | `.github/workflows/ci.yml:143` | Version de Node de la CI et de l'image en deux endroits. | **Non retenu.** |
| 7 | suggestion | `frontend/nginx.conf:14-24` | Pas d'en-têtes de sécurité. | **Non retenu** (à reprendre avec Keycloak, BIL-F27/F28). |
| 8 | suggestion | `frontend/src/vite-env.d.ts:8-10` | `ImportMeta` redéclaré. | **Non retenu.** |

Retenus tels quels par le développeur (relevés comme conformes en première review, confirmés en
validation 2) : chaîne `public@file` pour le front (`infra/consul/frontend.json:12`,
`infra/traefik/dynamique.yml:4,72-73`), script `typecheck` (`frontend/package.json:10`), images
`node:22.20.0-alpine` et `nginx-unprivileged:1.28.0-alpine` épinglées par tag sans digest.

Nouveaux points : aucun. Vérifications faites sur les changements de la validation 2 :

- Le verrou de `playwright.config.ts` suit le même modèle que `^frontend/e2e/` dans `TESTS`
  (chemin relatif à la racine ; `git_sur` normalise `\` et `./`) ; il ne s'applique pas à
  l'étape `squelette`, où le fichier est posé, ni à `tests`.
- `test_hooks.py` : un test ajouté, aucun retiré ni affaibli.
- Nginx non privilégié : `root /usr/share/nginx/html` et le cache (`/assets/` immutable, `/` en
  `no-cache` avec repli SPA) inchangés.

## Grille

| Axe | Résultat |
|---|---|
| Ticket et contrat | conforme (étapes 1 à 6, CA1 à CA3, décisions des validations 1 et 2) ; aucun contrat d'API concerné |
| Rules | conforme (`frontend.md`, `securite.md`, `git.md` : rien n'est commité) |
| Sécurité | conforme : aucun secret, aucune route protégée concernée ; Nginx sans root (point 5) ; `/api` et `/auth` ne tombent plus sur la chaîne sans vérification (point 1) ; en-têtes de sécurité non retenus (point 7) |
| Résilience | conforme : une panne d'API répond 404 de la gateway, plus 200 HTML (point 1) ; aucun appel entre services ni événement |
| Tests | conforme : `passWithNoTests` retiré (point 2), config Playwright verrouillée et testée (point 4) ; aucun test affaibli. Faute de commits, on ne peut pas prouver qu'aucun test n'a changé après l'étape `tests` |
| Lisibilité | bonne : commentaires à jour après le passage en 8080 et la nouvelle règle |
