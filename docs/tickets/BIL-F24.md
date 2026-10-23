# BIL-F24 : Workflow : skills /write-tests, /open-pr et /smoke-tests

- **Branche** : `chore/bil-f24-skills`
- **Dépend de** : BIL-F23

## Objectif

Écrire les trois skills appelés par `/ticket` ou utilisés à part : répartition des tests,
ouverture de PR et smoke tests.

## Étapes

- [x] 1. `/write-tests` : refuse un plan qui a encore des questions ; envoie les cas `unitaire`
  et `composant` à `unit-test-writer`, `intégration` et `parcours` à `integration-test-writer`,
  en parallèle ; un niveau absent n'est pas lancé ; vérifie le rouge par une mesure réelle
- [x] 2. `/open-pr` : refuse si un test est rouge ; commit avec l'ID du ticket, push,
  `gh pr create` (ticket, plan, review) ; ticket Notion en `IN REVIEW` avec le lien de la PR
- [x] 3. `/smoke-tests` : hors pipeline, `tests/smoke/` (marqueur `smoke`, exclu par défaut,
  `make test-smoke`) pour les parcours critiques de bout en bout
- [x] `/ticket` appelle désormais `/write-tests` et `/open-pr`

## Critères d'acceptance

- [x] CA1 : `/write-tests` lance les deux agents en parallèle (essai réel : les deux appels
  d'agent dans le même message ; 8 tests rouges, tous sur une assertion, mesurés)
- [x] CA2 : la PR de ce ticket est ouverte par `/open-pr`, référence le ticket, et le statut
  Notion passe à IN REVIEW
- [x] CA3 : aucun skill ne merge (`tests/unit/test_skills_claude.py`, et le hook « Git sûr »
  bloque `gh pr merge`)

## Contraintes

- `/open-pr` refuse de s'exécuter si des tests sont rouges.

## Découvertes et correctifs

- **Marqueur déplacé de `.claude/etape` vers `.pipeline/etape`** : Claude Code protège chaque
  fichier de `.claude/` et refuse de l'écrire sans permission, même avec une règle `allow`. Le
  premier essai de `/write-tests` est resté bloqué à l'étape `squelette` (tests verrouillés).
- **Résultat inventé** : lors de ce premier essai, les deux agents ont rapporté honnêtement
  n'avoir rien écrit, mais la session principale a rendu un tableau de tests « rouges » qui
  n'existaient pas. `/write-tests` impose désormais de ne rendre que des résultats mesurés par
  pytest et de s'arrêter si un agent n'a rien écrit.
