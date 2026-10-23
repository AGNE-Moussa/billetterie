# Review : BIL-F25, Workflow : répétition complète sur le service echo

- Diff relu : `git diff` (travail non commité) et fichiers non suivis, quatrième review après
  corrections (30 fichiers : 22 modifiés, 8 nouveaux, sans ce rapport)
- Verdict : 0 bloquant, 2 à corriger, 1 suggestion

## Suivi de la review 3

| # (review 3) | Classement initial | Décision du développeur | État |
|---|---|---|---|
| 1 | bloquant : guillemets lus autrement que par le shell | retenu | **corrigé** : liste de caractères refusés partout (`limiter_commandes.py:34`), `\`, `$`, `` ` ``, `{ }`, `< >`, `\r` et non ASCII compris ; un texte entre guillemets ne peut plus contenir d'échappement, donc il se lit pareil dans les deux shells (l.36) ; parenthèses refusées hors guillemets (l.89) ; options d'écriture cherchées après retrait des guillemets (l.92). Un test par écart relevé (`tests/unit/test_agents_claude.py:238-245`) |
| 2 | à corriger : arguments qui font écrire une commande permise | retenu, « resserrer + documenter » | **corrigé en partie** : `make` limité à des cibles (l.61), `docker compose cp/run/exec` refusés (l.63), options de configuration de pytest refusées (l.65-74), tests l.246-256. Limite connue documentée (l.21-22 et rétro l.63). Restent deux écarts avec la décision, point 1 ci-dessous |
| 3 | à corriger : rétro qui garantissait trop | retenu | **corrigé** : plus de garantie générale (`docs/retro-workflow.md:49`), review 4 renvoyée au rapport (l.21), section « Leçon » (l.57-63). La l.5 parle de la PR au futur (« qui suit cette rétrospective ») : acceptable |
| 4 | suggestion : documenter le filtre au mieux | retenu | **corrigé** dans la docstring (l.9-15) et la rétro ; pas dans `docs/workflow.md` (point 3) |

## Points

| # | Classement | Fichier:ligne | Constat | Attendu |
|---|---|---|---|---|
| 1 | à corriger | `.claude/hooks/limiter_commandes.py:38-40`, `:65-74` | La review 3 (point 2d) citait `pytest --debug=<fichier>`, qui écrit un fichier choisi par l'appelant. Cette option n'est ni dans `OPTIONS_ECRITURE` ni dans les options pytest refusées, et elle n'est pas non plus dans la limite connue (l.21-22). Même chose pour `npx --prefix frontend playwright` (`integration-test-writer.md:14`), dont des sous-commandes écrivent un fichier de sortie (review 3, point 2c) : la limite connue ne cite que les scripts npm et Vitest. | Ajouter `--debug` à `OPTIONS_ECRITURE`, avec un test dans `test_la_lecture_ne_cache_aucune_ecriture`. Sinon, l'inscrire dans la limite connue, avec Playwright, dans la docstring et dans `docs/retro-workflow.md:63`. |
| 2 | à corriger | `.claude/hooks/limiter_commandes.py:63` | Pour `docker compose`, le hook refuse trois sous-commandes nommées. C'est une liste noire, alors que la review 3 recommandait d'autoriser seulement des sous-commandes nommées (`up`, `down`, `ps`, `logs`), et que la docstring (l.4-5) pose le principe de la liste blanche. Toute sous-commande qui n'est pas citée passe, sans être comptée dans la limite connue. | Soit une liste blanche de sous-commandes (`up`, `down`, `ps`, `logs`, `build` si utile), avec un test, soit une limite connue qui le dit. |
| 3 | suggestion | `docs/workflow.md:166-170` | La nature de filtre au mieux de `limiter_commandes`, avec sa limite connue, est écrite dans la docstring et dans la rétro, mais pas dans la conception du pipeline. C'est pourtant là qu'un lecteur cherche ce que les hooks garantissent. | Une phrase dans la section des hooks de `docs/workflow.md`, qui renvoie à la docstring. |

## Grille

| Axe | Résultat |
|---|---|
| Ticket et contrat | Fonctionnalité conforme à `openapi.yaml` (`listerEchos`, `EchoPage`, 401/403/422, bornes, tri, page vide), sans changement depuis la review 3. CA1 à CA3 remplis (rétro complète et mesurée). |
| Rules | Conforme : migration 0003, couches, typage, convention de pagination, git (rien de commité, aucune attribution). |
| Sécurité | Route conforme (`exige_scopes("echos:read")`, jeton revérifié). Workflow : le bloquant de la review 3 est levé ; points 1 et 2 sur des arguments encore permis. Aucun secret. Ni les places ni les revendeurs ne sont concernés. |
| Résilience | Sans objet : aucun appel entre services, aucun événement. |
| Tests | Aucun test affaibli. `test_agents_claude.py` n'a reçu que des cas ajoutés (lectures permises, contournements refusés), plus le chemin `docs/conventions.md` de `contract-writer`, conforme à la friction 1. Rien n'est commité : `git log` ne peut pas prouver que le contrat n'a pas bougé depuis l'étape `tests`. |
| Lisibilité | Bonne : docstring honnête sur les limites, un commentaire par motif, pas de code mort. Point 3. |
