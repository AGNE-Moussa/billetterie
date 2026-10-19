# BIL-F04 : CI GitHub Actions et hook Git commit-msg

- **Branche** : `ci/bil-f04-pipeline`
- **Dépend de** : BIL-F01

## Objectif

Mettre en place une CI qui vérifie qualité, typage et tests à chaque PR, et refuser les messages
de commit hors convention.

## Étapes

- [x] 1. Workflow `ci.yml` : jobs `lint`, `types`, `unit`, `integration`, `contract`
- [x] 2. Cache uv entre les exécutions
- [x] 3. Job `frontend` (lint, Vitest, build) déclenché seulement si `frontend/**` change
- [x] 4. Hook `commit-msg` versionné dans `.githooks/`, activé par `make init`
- [ ] 5. Rendre les jobs obligatoires dans la protection de `main`

## Critères d'acceptance

- [ ] CA1 : une PR avec une erreur ruff ou mypy est rouge
- [x] CA2 : un commit `update stuff` est refusé localement
- [ ] CA3 : la CI complète dure moins de 10 minutes

## Contraintes

- Aucun secret dans les workflows ; les secrets éventuels passent par les secrets GitHub.
