---
name: open-pr
description: "Dernière étape du pipeline (docs/workflow.md) : vérifie que tous les tests passent, commit en Conventional Commits avec l'ID du ticket, push, ouvre la PR (qui cite le ticket, le plan et la review) avec gh pr create, puis passe le ticket Notion en IN REVIEW avec le lien de la PR. Ne merge jamais."
argument-hint: "<Ticket ID, par exemple BIL-006>"
---
Tu ouvres la PR du ticket **$ARGUMENTS**. Tu ne merges **jamais** : le merge est humain (le hook
« Git sûr » bloque `gh pr merge`). Tu ne poses jamais `TO TEST` ni `✅ DONE`.

## 1. Refuser si quelque chose est rouge

Écris `pr` dans `.pipeline/etape` si un marqueur existe. Lance `make lint`, `make typecheck`,
`make test-unit`, puis les tests d'intégration modifiés par la branche
(`git diff --name-only main...HEAD` et `git status --short` : `uv run pytest <ces fichiers>`).
Si une commande échoue, **arrête-toi** : montre l'échec, n'ouvre pas de PR. (La suite complète
d'intégration tourne en CI.)

Vérifie aussi que la branche courante est celle du ticket (propriété `Branche` dans Notion) et
qu'elle n'est pas `main`.

## 2. Commit et push

- Ajoute les fichiers du ticket (jamais `.env`, ni `.pipeline/etape`, ni un fichier d'essai).
- Message en Conventional Commits, en français, **avec l'ID du ticket**, sans ligne
  d'attribution : `feat(billets): verrouiller une place pendant l'achat (BIL-006)`. Corps :
  ce qui change et pourquoi, en quelques lignes.
- `git push -u origin <branche>`.

## 3. PR

`gh pr create --base main --head <branche> --title "<message de commit>" --body-file <fichier>`
avec un corps qui contient :

- le lien du ticket Notion ;
- le résumé de `docs/tickets/$ARGUMENTS.md` (critères cochés) ;
- le plan `docs/test-plans/$ARGUMENTS.md` et le rapport `docs/reviews/$ARGUMENTS.md` (chemins et
  verdict) ; « hors pipeline » s'ils n'existent pas ;
- les décisions validées par le développeur et les tests lancés.

Écris le fichier du corps dans le dossier temporaire de la session, pas dans le dépôt.

## 4. Notion

Passe `Agile Statut` du ticket à `IN REVIEW` et ajoute en commentaire le lien de la PR et le
verdict de la review. Supprime `.pipeline/etape`.

Termine en rappelant au développeur : vérifier la CI, merger lui-même, puis poser `TO TEST` et
`✅ DONE`.
