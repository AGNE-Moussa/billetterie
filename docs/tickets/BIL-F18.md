# BIL-F18 : Workflow : rules communes et rules du projet

- **Branche** : `chore/bil-f18-rules`
- **Dépend de** : BIL-F17

## Objectif

Écrire les fichiers de `.claude/rules/`, chacun limité par chemin, pour que les agents aient les
bonnes règles au bon moment.

## Étapes

- [x] 1. Rules communes : `python.md`, `tests.md`, `contrats-api.md`, `evenements.md`,
  `migrations.md`, `securite.md` (toujours), `git.md` (toujours), `frontend.md`
- [x] 2. Rules du projet : `places-concurrence.md` (services/billets, services/commandes) et
  `billets-qr.md` (services/billets)
- [x] 3. Chaque rule : 30 lignes au maximum, avec un exemple court de bon et de mauvais code

## Critères d'acceptance

- [x] CA1 : en ouvrant un fichier de `services/billets/`, `places-concurrence.md` est chargée.
  Vérifié par une session `claude -p` : `git.md` et `securite.md` dès le début,
  `places-concurrence.md`, `billets-qr.md` et `python.md` seulement après la lecture d'un
  fichier de `services/billets/`, aucune autre. À revérifier avec `/memory`.
- [x] CA2 : aucune rule ne dépasse 30 lignes (garanti par `tests/unit/test_rules_claude.py`)

## Contraintes

- Une règle qui doit être garantie devient un hook (BIL-F19), pas une phrase dans une rule.

## Choix techniques

- Les rules s'appuient sur le code réel du dépôt (`commun.http.ClientService`,
  `commun.erreurs.ErreurMetier`, `publier_plus_tard`, `consommateur_idempotent`, `commun.auth`).
- `python.md` couvre aussi `infra/**/*.py` (vérificateur), `tests.md` aussi les tests du front.
- Les exemples Python des rules sont formatés par ruff, comme le reste du dépôt.
