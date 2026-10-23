# BIL-F25 : Workflow : répétition complète sur le service echo

- **Branche** : `feat/bil-f25-repetition-echo`
- **Dépend de** : BIL-F24, BIL-F16
- **Service** : echo (support), workflow Claude

## Objectif

Faire passer un vrai petit ticket sur `services/echo` par tout le pipeline, de `/ticket` jusqu'à
la PR, pour valider le workflow avant le métier.

## Étapes

- [x] 1. Lancer `/ticket BIL-F25` : ce ticket lui-même sert de support. Fonctionnalité à
  livrer : `GET /api/v1/echos` paginé avec le scope `echos:read`.
- [x] 2. Suivre tout le pipeline, noter chaque friction (agent bavard, hook trop strict, contexte
  trop lourd).
- [x] 3. Corriger agents, skills ou hooks en conséquence dans la même branche.
- [x] 4. Rédiger `docs/retro-workflow.md` : ce qui a marché, ce qui a été changé.

## Critères d'acceptance

- [ ] CA1 : le pipeline va de la lecture Notion à la PR sans intervention hors des deux
  validations. **En partie** : en plus de la validation du contrat, de la validation 1 et des
  passages de la validation 2 (4 reviews), une question imprévue a été posée entre deux reviews
  (qui écrit `.claude/rules/`, Claude Code interdisant `.claude/` aux agents), comme le veut la
  règle « une décision non prévue remonte en question »
- [x] CA2 : les hooks ont bloqué au moins une action interdite pendant l'essai
  (`limiter_commandes` sur des commandes d'agents, le hook Stop sur des tests rouges,
  `proteger_fichiers` sur l'écriture d'un test à l'étape `review`)
- [x] CA3 : la rétrospective est écrite (`docs/retro-workflow.md`) et les corrections sont dans la
  PR

## Contraintes

- À partir de ce ticket, tous les tickets du board passent par `/ticket`.

## Décisions (validation du contrat)

- Réponse paginée commune `{elements, page, size, total}` : modèle générique `Page[T]` dans
  `libs/commun` (sous-classe `EchoPage(Page[EchoReponse])` pour garder le nom du contrat),
  convention à inscrire dans `docs/conventions.md`. Pagination à partir de 1 : `page` ≥ 1
  (1 par défaut), `size` de 1 à 100 (20 par défaut).
- Éléments : `EchoReponse` tel quel (champ `instance` compris).
- Tri par `cree_le` décroissant, sans paramètre de tri ; page au-delà de la fin : 200 avec
  `elements` vide ; aucun filtre.
- Scope `echos:read` ajouté au realm (`infra/keycloak/realm-billetterie.json`), donné par défaut
  au client `services`, par `implementer`.

## Décisions (validations 1 et 2)

- Plan : critères D1 à D6 validés ; départage du tri par `message` croissant ; paramètre inconnu
  ignoré (200) ; scope vérifié par un test unitaire du realm.
- Convention de pagination : `contract-writer` écrit `docs/conventions.md` ; `/ticket` recopie la
  rule dans `.claude/rules/contrats-api.md` (Claude Code interdit `.claude/` aux agents).
- `limiter_commandes` : commandes de lecture seule permises à tous les agents ; liste de
  caractères sûrs ; arguments de `make`, `docker compose` et `pytest` resserrés, le reste
  documenté comme limite connue.
- Suggestions retenues : index sur le tri (migration `0003`), bornes de pagination dans
  `libs/commun`, test realm côté `frontend`. Requête unique total et page non retenue.
- Après la review 4 (0 bloquant), corrections puis PR sans cinquième review.
