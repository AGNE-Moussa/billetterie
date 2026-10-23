# BIL-F23 : Workflow : serveur MCP Notion et skill /ticket

- **Branche** : `chore/bil-f23-skill-ticket`
- **Dépend de** : BIL-F22

## Objectif

Que `/ticket BIL-xxx` lise lui-même le ticket dans le board Notion du projet, puis orchestre tout
le pipeline sans aucun copier-coller.

## Étapes

- [x] 1. Serveur Notion en portée projet (`claude mcp add --transport http --scope project notion
  https://mcp.notion.com/mcp`) : `.mcp.json` versionné, sans jeton ; authentification par `/mcp`
- [x] 2. `.claude/skills/ticket/SKILL.md`, argument `<ID>` : recherche dans le board,
  dépendances, `DOING`, `docs/tickets/<ID>.md`, branche, contrat (si une route change), plan et
  validation 1, squelette, tests, implémentation, review et validation 2, PR, `IN REVIEW` ;
  marqueur `.claude/etape` à chaque étape ; reprise d'après le marqueur
- [x] 3. Notion indisponible : arrêt, jamais de ticket reconstitué de mémoire

## Critères d'acceptance (essais réels)

- [x] CA1 : `/ticket BIL-F16` affiche le ticket lu dans Notion (titre, objectif, critères,
  branche) sans aucune saisie
- [x] CA2 : BIL-F16 passe à DOING dans Notion au démarrage (statut ✅ DONE restauré après l'essai)
- [x] CA3 : `/ticket BIL-006` refusé avec la liste des bloquants (BIL-004, BACKLOG), rien modifié
- [x] CA4 : arrêt à la validation 1 (plan de BIL-F16) puis à la validation 2 (review, après
  reprise sur le marqueur `review`)
- [x] Étape 3 : sans Notion (session non interactive), le skill s'arrête sans rien modifier

## Contraintes

- Le skill ne passe jamais un ticket en `TO TEST` ou `DONE`.

## À savoir

- Le serveur projet `notion` doit être approuvé puis authentifié (`claude`, puis `/mcp`) ; le
  connecteur claude.ai Notion est aussi accepté par le skill. En session non interactive
  (`claude -p`), aucun des deux n'est disponible tant que le serveur projet n'est pas
  authentifié.
- `/write-tests` et `/open-pr` arrivent en BIL-F24 ; d'ici là, `/ticket` lance directement les
  deux écrivains et ouvre la PR lui-même.
- Le skill n'existe sur une branche qu'une fois mergé dans `main` (une branche créée depuis
  `main` avant le merge ne l'a pas).

## Corrigé au passage

- Étape 1e : un `docs/tickets/<ID>.md` existant n'est plus écrasé (relevé par `reviewer` lors de
  l'essai sur BIL-F16, ticket déjà livré). `tests/unit/test_skill_ticket.py` garde les règles du
  skill et vérifie que `.mcp.json` ne contient aucun jeton.
