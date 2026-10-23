---
name: ticket
description: "Lit un ticket du board Notion du projet (par son Ticket ID, par exemple BIL-006) et déroule tout le pipeline de docs/workflow.md : dépendances, statut DOING, docs/tickets/<ID>.md, branche, contrat, plan, squelette, tests, implémentation, review, PR. S'arrête aux validations humaines."
argument-hint: "<Ticket ID, par exemple BIL-006>"
---
Tu orchestres le pipeline du ticket **$ARGUMENTS**, décrit dans `docs/workflow.md`. Tu ne fais
toi-même que lire Notion, écrire `docs/tickets/`, poser le marqueur `.claude/etape` et lancer les
agents ; le travail est fait par les agents. Tu t'arrêtes à chaque validation humaine.

## Règles absolues

- **Notion est la seule source** : outils du serveur MCP Notion du projet (`mcp__notion__*`) ou
  du connecteur claude.ai (`mcp__claude_ai_Notion__*`). Si aucun ne répond, **arrête-toi** et
  dis-le : ne reconstitue jamais un ticket de mémoire ni d'après `docs/tickets/`.
- Statuts que tu poses : `DOING` (étape 1), `IN REVIEW` (étape 9). **Jamais** `TO TEST` ni
  `✅ DONE` : ils restent humains, après le merge. Aucun merge non plus (hook « Git sûr »).
- Une décision que le ticket ne prévoit pas remonte en question ; tu ne la tranches pas.
- Le marqueur `.claude/etape` ne change qu'après la décision humaine qui le justifie.

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
f. Crée la branche de la propriété `Branche` depuis `main` à jour (`git switch main`,
   `git pull`, `git switch -c <branche>`), puis écris `cadrage` dans `.claude/etape`.

## 2. Contrat (marqueur `contrat`), seulement si le ticket ajoute ou change une route

Écris `contrat` dans `.claude/etape`, lance l'agent `contract-writer`, puis affiche les routes
ajoutées et ses questions. **Validation du contrat : arrête-toi** et attends l'accord du
développeur (« à reprendre » relance `contract-writer` avec ses remarques). Sinon, passe à 3.

## 3. Plan (marqueur `plan`)

Écris `plan` dans `.claude/etape`, lance l'agent `test-planner`, puis affiche le résumé du plan
(cas par niveau, questions). **Validation 1 : arrête-toi.** Le plan n'est validé que lorsque le
développeur a répondu à toutes les questions ; reporte ses réponses en tête du plan
(section « Questions ») avant de continuer.

## 4. Squelette (marqueur `squelette`)

Écris `squelette` dans `.claude/etape`, lance l'agent `implementer` pour l'étape squelette
uniquement. Vérifie que le test de contrat passe (`uv run pytest -m contract`).

## 5. Tests (marqueur `tests`)

Écris `tests` dans `.claude/etape`. Lance le skill `/write-tests` (BIL-F24) ; s'il n'existe pas
encore, lance **en parallèle** les agents `unit-test-writer` et `integration-test-writer`.
Vérifie toi-même que chaque test rouge échoue sur une assertion (`uv run pytest ... -q`) ; un
test vert n'est admis que s'il ne vérifie qu'une garde du contrat.

## 6. Implémentation (marqueur `implementation`)

Écris `implementation` dans `.claude/etape`, lance l'agent `implementer` jusqu'au vert, puis
vérifie : `make lint`, `make typecheck`, `make test-unit` (et `make test-integration` si le
ticket a des tests d'intégration).

## 7. Review (marqueur `review`)

Écris `review` dans `.claude/etape`, lance l'agent `reviewer`, puis affiche le verdict et les
points bloquants. **Validation 2 : arrête-toi** et attends la décision du développeur. Les points
qu'il renvoie repartent vers `implementer` (marqueur `implementation`), puis nouvelle review.

## 8. PR (marqueur `pr`)

Écris `pr` dans `.claude/etape`. Lance le skill `/open-pr` (BIL-F24) ; s'il n'existe pas encore :
commit en Conventional Commits sans ligne d'attribution, `git push -u`, `gh pr create` avec un
corps qui cite le ticket, le plan et la review.

## 9. Fin

Passe le ticket en `IN REVIEW` dans Notion, ajoute le lien de la PR en commentaire, supprime
`.claude/etape`, puis rappelle au développeur : vérifier la CI, merger lui-même, poser
`TO TEST` puis `✅ DONE`.

## Reprise

Si `.claude/etape` existe déjà et que la branche courante est celle du ticket, reprends à
l'étape du marqueur au lieu de recommencer (sans repasser le ticket en `DOING`).
