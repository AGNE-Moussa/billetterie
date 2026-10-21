# BIL-F20 : Workflow : agents contract-writer et test-planner

- **Branche** : `chore/bil-f20-test-planner`
- **Dépend de** : BIL-F19

## Objectif

Créer l'agent qui transforme un ticket, back ou front, en plan de tests étiqueté, soumis à la
validation du développeur, et l'agent `contract-writer` qui écrit le contrat OpenAPI avant lui
quand une route change.

## Étapes

- [x] 1. `.claude/agents/test-planner.md` : Read, Grep, Glob, Write ; écriture limitée à
  `docs/test-plans/*.md` par un hook déclaré dans l'en-tête de l'agent
- [x] 2. Entrées : `docs/tickets/<ID>.md`, contrat, rules du service, `docs/front/` pour le front
- [x] 3. Sortie : `docs/test-plans/<ID>.md`, cas nommés par critère, niveau, données synthétiques
- [x] 4. Front : un cas `composant` par état d'écran, au plus un `parcours` par critère
- [x] 5. Billets ou Commandes : au moins un cas de concurrence
- [x] 6. `.claude/agents/contract-writer.md` : Read, Grep, Glob, Write, Edit ; écriture limitée à
  `services/*/openapi.yaml` ; forme calquée sur `services/echo/openapi.yaml`

## Critères d'acceptance (vérifiés par des sessions `claude -p` réelles)

- [x] CA1 : sur BIL-006, chaque critère a des cas (10, 6 et 9), niveaux `unitaire` et
  `intégration` seulement, un cas de concurrence par critère, 7 questions en tête du plan
- [x] CA2 : `test-planner` invité à écrire `tests/unit/test_essai_agent.py` est bloqué par son
  hook ; aucun fichier créé (aussi couvert par `tests/unit/test_agents_claude.py`)
- [x] CA3 : sur BIL-019, 27 cas `composant`, 3 `parcours` (au plus un par critère), aucun cas
  `intégration` ; états chargement, vide, erreur, succès couverts ; 13 questions
- [x] CA4 : sur BIL-006, `contract-writer` écrit `services/billets/openapi.yaml` conforme aux
  conventions (`/api/v1/places`, `page` et `size`, `operationId` en camelCase, Problem Details
  401, 409 `SEAT_ALREADY_TAKEN`, 422, `HTTPBearer` sur les écritures) ; invité à écrire
  `services/billets/src/billets/routes.py`, il est bloqué

Les fichiers produits par les essais (contrat de billets, plans de BIL-006 et BIL-019) ne sont pas
commités : ils n'ont passé aucune validation humaine et seront refaits par le pipeline.

## Contraintes

- Le plan n'invente aucune règle métier : une ambiguïté devient une question en tête du plan.

## Décisions et correctifs (validés par le développeur)

- Hooks d'agent (`limiter_ecriture.py`) dans l'en-tête de chaque agent, actifs seulement pendant
  qu'il travaille ; aucun des deux agents n'a accès au shell.
- Workspace uv en liste explicite (`libs`, `services/echo`, `infra/verificateur`) au lieu de
  `services/*` : le contrat d'un nouveau service existe avant son code, et uv refusait de
  démarrer sans son `pyproject.toml` (`tests/unit/test_workspace.py` garde la cohérence).
- Hooks lancés par `uv run --no-project python` : ils ne dépendent plus du workspace, qui peut
  être momentanément invalide (sinon tous les outils étaient bloqués par une erreur uv).

## À reprendre dans les tickets concernés

- BIL-006 : les questions du plan d'essai sont de bonnes questions de cadrage, en particulier
  la réponse quand un autre client lève le verrou, et l'identifiant stocké dans le verrou
  (`sub` de l'appelant plutôt que `azp`). L'exemple de `.claude/rules/places-concurrence.md`
  met un identifiant de commande comme valeur du verrou : à aligner sur la décision prise.
- BIL-019 : dépend aussi du squelette front (BIL-F26 à BIL-F28) ; le mode dégradé du cache doit
  être déclaré dans le contrat du catalogue.
