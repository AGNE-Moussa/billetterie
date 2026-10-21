# BIL-F19 : Workflow : hooks de garantie

- **Branche** : `chore/bil-f19-hooks`
- **Dépend de** : BIL-F18, BIL-F04

## Objectif

Déclarer dans `.claude/settings.json` les hooks qui rendent impossibles les erreurs graves, quel
que soit l'agent.

## Étapes

- [x] 1. PostToolUse sur Edit et Write : `.py` → `ruff format` puis `ruff check` ; `.ts`, `.tsx`,
  `.js` de `frontend/` → `prettier --write` puis `eslint` ; erreurs renvoyées à l'agent
  (`formater.py`)
- [x] 2. PreToolUse sur Edit, Write et NotebookEdit : `.env*` (sauf `.env.example`), fichiers de
  secrets, toute écriture du projet sur `main` (`proteger_fichiers.py`)
- [x] 3. Tests verrouillés aux étapes `implementation`, `review` et `pr` (`.claude/etape`), et
  contrat verrouillé hors de l'étape `contrat` (décision : inclus dans ce ticket)
- [x] 4. PreToolUse sur Bash et PowerShell : `git push --force`, push et `git merge` vers `main`,
  `gh pr merge`, écritures par le shell dans `.env`, les tests verrouillés et le contrat
  (`git_sur.py`)
- [x] 5. Stop : tests rapides de ce qui a changé (pytest unitaire si du Python a changé, Vitest
  si le front a changé) ; en cas d'échec, l'agent doit corriger une fois (`tests_rapides.py`)
- [x] 6. Scripts dans `.claude/hooks/`, testés par `tests/unit/test_hooks.py`

## Critères d'acceptance

- [x] CA1 : écrire dans un `.env` est bloqué avec un message clair (session `claude -p` réelle)
- [x] CA2 : avec le marqueur `implementation`, toute écriture dans les tests est refusée (session
  `claude -p` réelle ; écritures par le shell couvertes par les tests unitaires)
- [x] CA3 : `gh pr merge` est refusé (session `claude -p` réelle)
- [x] CA4 : un `.tsx` mal formaté est corrigé par Prettier et une erreur ESLint est renvoyée
  (test avec les vrais outils de `frontend/node_modules`)
- [x] CA5 : un tour qui ne touche que le front lance Vitest et pas pytest, et inversement
  (sélection testée ; Vitest arrive avec le squelette Vite, BIL-F26)

## Contraintes

- Scripts Python, bibliothèque standard seulement, sans réseau.

## Décisions (validées par le développeur)

- Prettier et ESLint installés dès ce ticket (`frontend/package.json`, versions épinglées) ; la
  CI lance `test` et `build` du front avec `--if-present` jusqu'à BIL-F26.
- Hook Stop : l'agent doit corriger une fois ; au second arrêt (`stop_hook_active`), il est
  laissé finir avec l'échec signalé.
- Hook « Contrat protégé » inclus.

## Limites

- Détection des écritures par le shell heuristique (voir `docs/workflow.md`, section 7).
- Les hooks s'appliquent aussi au développeur dans Claude Code : sur `main`, créer d'abord la
  branche du ticket.
