# BIL-F03 : CLAUDE.md du projet

- **Branche** : `chore/bil-f03-claude-md`
- **Dépend de** : BIL-F02

## Objectif

Écrire un `CLAUDE.md` court qui donne à toute session Claude Code la pile, les commandes et le
pipeline du projet.

## Étapes

- [x] 1. `CLAUDE.md` racine (moins de 80 lignes) : pile, commandes (`make up`, `make test`,
  `uv run pytest tests/unit`), arborescence, lien vers `docs/conventions.md`
- [x] 2. Section Notion : identifiant du board, préfixe `BIL-`, valeurs de statut utilisées par
  `/ticket`
- [x] 3. Section pipeline : un ticket = une branche = une PR, aucun agent ne merge, une décision
  imprévue remonte en question
- [x] 4. `frontend/CLAUDE.md` court (commandes npm, conventions React)

## Critères d'acceptance

- [x] CA1 : le `CLAUDE.md` racine fait moins de 80 lignes
- [x] CA2 : l'identifiant du board Notion et le préfixe `BIL-` y figurent
- [x] CA3 : une nouvelle session Claude Code sait citer les commandes de test sans les chercher

## Contraintes

- Aucune règle détaillée dans `CLAUDE.md` : elles vont dans `.claude/rules/` (BIL-F18).
