# BIL-F22 : Workflow : agents implementer et reviewer

- **Branche** : `chore/bil-f22-implementer-reviewer`
- **Dépend de** : BIL-F21

## Objectif

Créer l'agent qui code jusqu'au vert sans toucher aux tests, et l'agent qui relit le diff en
lecture seule.

## Étapes

- [x] 1. `implementer.md` : écrit dans `services/*/src/`, les migrations, `libs/`, `infra/`,
  `frontend/src/`, `pyproject.toml` et `compose.yaml`, jamais dans les tests ni les contrats
  (exclusions `!**/tests/**`, `!**/*.test.tsx`, `!frontend/e2e/**`, `!**/openapi.yaml`) ;
  commandes de vérification en liste blanche
- [x] 2. `reviewer.md` : Read, Grep, Glob, `git diff`, `git log`, `git show`, `git status` ;
  écrit seulement `docs/reviews/<ID>.md`
- [x] 3. Grille : ticket et contrat, rules, sécurité, résilience, tests, lisibilité ; chaque
  point classé bloquant, à corriger ou suggestion, avec fichier et ligne
- [x] 4. Priorités : aucune place vendue deux fois, un revendeur ne voit que ses commandes
- [x] 5. Étape « squelette » d'`implementer` (ajoutée en BIL-F21)

## Critères d'acceptance (chaîne complète réelle sur un ticket d'essai, non commité)

Ticket d'essai « supprimer un echo » : contrat (`contract-writer`), plan (`test-planner`,
questions répondues à la validation 1), squelette (`implementer`), tests (les deux écrivains en
parallèle), code jusqu'au vert (`implementer`), review (`reviewer`).

- [x] CA1 : invité explicitement à modifier un test, `implementer` est bloqué deux fois (Edit
  par `proteger_fichiers.py`, `sed -i` par `git_sur.py`) ; fichier de test intact (même md5)
- [x] CA2 : le rapport suit la grille, classe chaque point (0 bloquant, 1 à corriger, 2
  suggestions) avec fichier et ligne, traite d'abord les deux priorités du projet
- [x] CA3 : le squelette respecte le contrat (test de contrat vert) ; les 13 tests rouges
  écrits ensuite échouent tous sur une assertion (`501 == 204`, `501 == 404`, `409 == 201`,
  `200 == 404`), aucune exception ; 3 verts (2 gardes du scope, 1 signalé) ; après
  l'implémentation, les 34 tests d'echo passent, lint et typecheck aussi

## Contraintes

- Le reviewer ne corrige jamais lui-même : il décrit, l'implementer corrige.

## Corrigés au passage

- En-têtes YAML des agents : description entre guillemets (un « : » rendait `implementer.md`
  illisible) ; `tests/unit/test_agents_claude.py` vérifie désormais tous les agents.
- `limiter_ecriture.py` : motifs d'exclusion « ! », prioritaires.
- Message de refus de `git_sur.py` aligné sur `proteger_fichiers.py`.
