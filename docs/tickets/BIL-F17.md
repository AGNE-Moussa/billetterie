# BIL-F17 : Workflow : conception de l'outillage .claude/

- **Branche** : `docs/bil-f17-conception-workflow`
- **Dépend de** : BIL-F03

## Objectif

Décrire dans `docs/workflow.md` le pipeline d'un ticket et le rôle exact de chaque agent, skill,
rule et hook avant de les écrire.

## Étapes

- [x] 1. Recopier dans `docs/workflow.md` la section Workflow Claude de la page Notion du projet
  (sections 1 à 7)
- [x] 2. Diagramme Mermaid du pipeline : `/ticket` lit Notion, contrat (si une route change),
  plan, validation 1, tests, implémentation, review, validation 2, PR, merge humain (section 8)
- [x] 3. Tableau des droits : quel agent lit, écrit où, lance quoi (section 10)
- [x] 4. Marqueurs d'étape (`.claude/etape`) utilisés par les hooks (section 11)

## Critères d'acceptance

- [x] CA1 : chaque étape du pipeline a un responsable unique (agent, skill ou humain) : tableau de
  la section 9
- [x] CA2 : les deux points de validation humaine et le merge humain sont explicites (sections 8
  et 9 ; plus la validation du contrat, quand une route change)

## Contraintes

- Aucun fichier `.claude/` créé dans ce ticket : seulement la conception.

## Décisions (validées par le développeur)

- Agent dédié `contract-writer`, avec sa propre validation, quand un ticket ajoute ou change une
  route ; hook « Contrat protégé ».
- Le hook « Git sûr » bloque `gh pr merge` sans exception : le développeur merge lui-même.
