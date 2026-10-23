---
name: ticket
description: "Lit un ticket du board Notion du projet (par son Ticket ID, par exemple BIL-006) et déroule tout le pipeline de docs/workflow.md : dépendances, statut DOING, docs/tickets/<ID>.md, branche, contrat, plan, squelette, tests, implémentation, review, PR. S'arrête aux validations humaines."
argument-hint: "<Ticket ID, par exemple BIL-006>"
---
Tu orchestres le pipeline du ticket **$ARGUMENTS**, décrit dans `docs/workflow.md`. Tu ne fais
toi-même que lire Notion, écrire `docs/tickets/`, poser le marqueur `.pipeline/etape` et lancer les
agents ; le travail est fait par les agents. Tu t'arrêtes à chaque validation humaine.

## Règles absolues

- **Notion est la seule source** : outils du serveur MCP Notion du projet (`mcp__notion__*`) ou
  du connecteur claude.ai (`mcp__claude_ai_Notion__*`). Si aucun ne répond, **arrête-toi** et
  dis-le : ne reconstitue jamais un ticket de mémoire ni d'après `docs/tickets/`.
- Statuts posés : `DOING` (étape 1), `IN REVIEW` (par `/open-pr`, étape 8). **Jamais** `TO TEST` ni
  `✅ DONE` : ils restent humains, après le merge. Aucun merge non plus (hook « Git sûr »).
- Une décision que le ticket ne prévoit pas remonte en question ; tu ne la tranches pas.
- Le marqueur `.pipeline/etape` ne change qu'après la décision humaine qui le justifie.

## 1. Cadrage (marqueur `cadrage`)

a. Board : `collection://628b2884-0d14-44a0-a153-8a844e530b8d` (voir `CLAUDE.md`). Cherche la
   ligne dont `Ticket ID` vaut exactement `$ARGUMENTS` (requête sur la base). Aucune ligne ou
   plusieurs : arrête-toi et dis-le.
b. Pour chaque ticket de `Dépend de`, lis son `Agile Statut`. Si l'un n'est pas `✅ DONE`,
   **arrête-toi** en listant les bloquants (ID, titre, statut) ; ne change rien dans Notion.
c. Lis la page du ticket et **affiche** son titre, son objectif, ses critères et sa branche.
d. Passe `Agile Statut` à `DOING`.
e. Écris `docs/tickets/$ARGUMENTS.md` avec **seulement** : titre, branche, dépendances, service,
   objectif, étapes (cases à cocher), critères d'acceptance, contraintes. Pas la théorie.
   S'il existe déjà, **ne l'écrase pas** (il porte peut-être l'avancement, les décisions et les
   résultats d'un passage précédent) : signale-le et demande au développeur s'il faut le garder.
f. Crée la branche de la propriété `Branche` depuis `main` à jour (`git switch main`,
   `git pull`, `git switch -c <branche>`), puis écris `cadrage` dans `.pipeline/etape` (crée le
   dossier `.pipeline/` si besoin, ignoré par Git).

## 2. Contrat (marqueur `contrat`), seulement si le ticket ajoute ou change une route

Écris `contrat` dans `.pipeline/etape`, lance l'agent `contract-writer`, puis affiche les routes
ajoutées et ses questions. **Validation du contrat : arrête-toi** et attends l'accord du
développeur (« à reprendre » relance `contract-writer` avec ses remarques). Si le contrat fixe une
forme commune à tous les services, `contract-writer` l'écrit dans `docs/conventions.md` et rend la
ligne de rule : recopie-la toi-même dans `.claude/rules/contrats-api.md` (Claude Code interdit
`.claude/` aux agents). Sinon, passe à 3.

## 3. Plan (marqueur `plan`)

Écris `plan` dans `.pipeline/etape`, lance l'agent `test-planner`, puis affiche le résumé du plan
(cas par niveau, questions). **Validation 1 : arrête-toi.** Le plan n'est validé que lorsque le
développeur a répondu à toutes les questions ; reporte ses réponses en tête du plan
(section « Questions ») avant de continuer.

## 4. Squelette (marqueur `squelette`)

Écris `squelette` dans `.pipeline/etape`, lance l'agent `implementer` pour l'étape squelette
uniquement. Vérifie que le test de contrat passe (`uv run pytest -m contract`).

## 5. Tests (marqueur `tests`)

Lance le skill `/write-tests $ARGUMENTS` : il refuse un plan qui a encore des questions, pose le
marqueur `tests`, lance en parallèle les écrivains utiles et vérifie que chaque test rouge échoue
sur une assertion.

## 6. Implémentation (marqueur `implementation`)

Écris `implementation` dans `.pipeline/etape`, lance l'agent `implementer` jusqu'au vert, puis
vérifie : `make lint`, `make typecheck`, `make test-unit` (et `make test-integration` si le
ticket a des tests d'intégration).

## 7. Review (marqueur `review`)

Écris `review` dans `.pipeline/etape`, lance l'agent `reviewer`, puis affiche le verdict et les
points bloquants. **Validation 2 : arrête-toi** et attends la décision du développeur. Les points
qu'il renvoie repartent vers `implementer` (marqueur `implementation`) ; refais alors les
vérifications de l'étape 6 (le hook Stop est suspendu pendant `implementation`), puis nouvelle
review.

## 8. PR (marqueur `pr`)

Lance le skill `/open-pr $ARGUMENTS` : il refuse si un test est rouge, commit avec l'ID du
ticket, pousse, ouvre la PR, passe le ticket en `IN REVIEW` avec le lien de la PR et supprime
`.pipeline/etape`.

## 9. Fin

Rappelle au développeur : vérifier la CI, merger lui-même, poser `TO TEST` puis `✅ DONE`.

## Reprise

Si `.pipeline/etape` existe déjà et que la branche courante est celle du ticket, reprends à
l'étape du marqueur au lieu de recommencer (sans repasser le ticket en `DOING`).
