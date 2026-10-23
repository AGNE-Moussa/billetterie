# Rétrospective du workflow (BIL-F25)

Répétition complète du pipeline (`docs/workflow.md`) sur une vraie fonctionnalité du service
echo : `GET /api/v1/echos`, paginé, protégé par le scope `echos:read`. Le ticket a été déroulé
par `/ticket BIL-F25`, de la lecture Notion jusqu'à l'ouverture de la PR par `/open-pr`, qui
suit cette rétrospective.

## Déroulé

| Étape | Agent ou skill | Résultat mesuré |
|---|---|---|
| Cadrage | `/ticket` | Ticket lu dans Notion, `DOING`, `docs/tickets/BIL-F25.md`, branche |
| Contrat | `contract-writer` | Route `listerEchos`, schéma `EchoPage` ; 6 questions, tranchées à la validation du contrat |
| Plan | `test-planner` | 24 cas (19 unitaires, 5 intégration) ; 4 questions, tranchées à la validation 1 |
| Squelette | `implementer` | Route en 501 avec ses gardes, `Page[T]`, signatures vides ; test de contrat vert |
| Tests | `/write-tests` (2 agents en parallèle) | 18 rouges, tous sur une assertion ; 19 verts admis (10 gardes, 2 structures, 7 existants) |
| Implémentation | `implementer` | 54 tests du ticket verts ; `make lint`, `make typecheck`, `make test-unit` verts |
| Review 1 | `reviewer` | 0 bloquant, 2 à corriger, 4 suggestions ; 2 + 3 retenus et corrigés dans la branche |
| Review 2 | `reviewer` | 1 bloquant (failles du nouveau `limiter_commandes`), 2 à corriger, 2 suggestions ; tous corrigés |
| Review 3 | `reviewer` | 1 bloquant (guillemets lus autrement que par le shell), 2 à corriger, 1 suggestion ; tous traités |
| Review 4 | `reviewer` | 0 bloquant, 2 à corriger (`pytest --debug`, `docker compose` en liste noire), 1 suggestion ; corrigés avant `/open-pr`, sans nouvelle review (décision du développeur) |

Interventions humaines : la validation du contrat, la validation 1 (plan) et la validation 2
(review, à chaque passage), plus une question imprévue (qui écrit les rules, friction 1). Aucune
autre (CA1).

## Ce qui a marché

- **Contrat d'abord** : les questions du contrat (forme de la page, bornes, tri, page au-delà
  de la fin) ont été posées avant toute ligne de code ; aucune n'a ressurgi plus tard.
- **Squelette avant les tests** : aucun test rouge pour une mauvaise raison (zéro `ImportError`).
- **Écrivains en parallèle** : chaque niveau de test a un seul auteur ; aucun conflit de fichier.
- **Verrous** : pendant l'implémentation, aucun test ni contrat n'a pu être modifié ; l'implementer
  a signalé ses doutes au lieu de toucher aux tests.
- **Hooks** (CA2) : pendant l'essai, `limiter_commandes` a refusé aux agents des commandes hors de
  leur liste, et le hook Stop a bloqué la fin d'un tour tant que des tests étaient rouges. Lors
  des essais du workflow (BIL-F19 à BIL-F24), les hooks avaient aussi bloqué l'écriture de tests
  verrouillés, `sed -i` sur un test et `gh pr merge`. Pendant les corrections, `proteger_fichiers` a aussi
  refusé à la session principale l'écriture d'un test à l'étape `review`.
- **Review en boucle** : la deuxième review a trouvé un bloquant dans une correction du workflow
  lui-même ; la boucle validation 2 → corrections → nouvelle review l'a arrêté avant la PR.
- **Aucun résultat sans mesure** : chaque tableau de résultats vient d'une commande lancée.

## Frictions et corrections

| # | Friction | Correction (dans cette PR) |
|---|---|---|
| 1 | Aucun agent ne pouvait écrire `docs/conventions.md`, alors que la pagination devenait une convention commune | `contract-writer` écrit aussi `docs/conventions.md` quand un contrat fixe une forme commune, et rend la ligne de rule ; `/ticket` la recopie dans `.claude/rules/contrats-api.md`, car Claude Code refuse à tout agent l'écriture dans `.claude/`, même permise par le hook (constaté à l'essai) |
| 2 | `limiter_commandes` refusait des lectures inoffensives (`cat`, `tail`, `head`, pipes, `cd`, `git -C`) : les agents perdaient des tours | Commandes de lecture seule permises à tous les agents, `cd` et `git -C` acceptés. Les reviews 2 et 3 ont trouvé, à chaque fois, des écritures qui passaient encore (`&` seul, `sort -o`, `--output`, `<(...)`, puis des guillemets échappés ou typographiques). Le hook est passé d'une liste de caractères dangereux à une liste de caractères sûrs : `` \ $ ` { } < > ``, le retour chariot et le non-ASCII sont refusés partout, et les arguments qui font écrire `make`, `docker compose` et `pytest` sont filtrés. Chaque contournement relevé a son test |
| 3 | Le hook Stop relançait les tests à chaque tour de la session principale pendant que l'implementer travaillait en fond, et exigeait de corriger des rouges attendus | Hook suspendu aussi à l'étape `implementation` ; `/ticket` (étape 6) mesure le vert une fois l'agent terminé |
| 4 | La règle des verts admis ne couvrait que les gardes 401/403/422 ; les tests de forme (`Page[T]`, `EchoPage`) ont dû être admis à la main | Les verts admis couvrent aussi la forme d'un schéma du contrat (écrivains, `/write-tests`, `docs/workflow.md`) |
| 5 | L'implementer demandait la validation des noms internes du squelette, une validation que le pipeline ne prévoit pas | Les noms techniques internes sont libres (`.claude/rules/python.md`), sans validation |
| 6 | Le serveur MCP Notion du projet n'est pas chargé dans une session ouverte avant son activation | Pas de correctif : le connecteur claude.ai a pris le relais (prévu par `/ticket`). Ouvrir une nouvelle session après `/mcp` |
| 7 | Les définitions d'agents (comme les skills) sont lues au démarrage de la session : un agent corrigé en cours de session garde son ancienne version, et `contract-writer` a d'abord refusé d'écrire la convention | Pas de correctif possible : un agent ou un skill modifié s'essaie dans une session neuve (`claude -p`) |
| 8 | Les critères d'un ticket de workflow ne sont pas des comportements testables : `test-planner` a dû dériver des critères fonctionnels (D1 à D6), validés à la validation 1 | Pas de correctif : c'est le rôle de la validation 1 ; les tickets métier ont des critères testables |

## Leçon

Un filtre de texte ne lit jamais une commande exactement comme bash ou PowerShell : chercher les
caractères dangereux est une course perdue d'avance. `limiter_commandes` n'accepte donc que des
caractères sûrs et refuse dans le doute ; il reste un filtre au mieux, une défense parmi
d'autres (`proteger_fichiers`, `git_sur`, la review qui vérifie que les tests n'ont pas changé,
la CI). Limite connue : les scripts npm et les options de Vitest et de Playwright peuvent encore
écrire ; `docker compose` est limité à une liste blanche de sous-commandes. La limite est
décrite dans `docs/workflow.md` (section 10).

## Points ouverts, pour les tickets métier

- Le total et la page sont lus par deux requêtes : simple et correct à cette échelle ; une
  fonction de fenêtre (`count(*) OVER ()`) les réunirait si la volumétrie le demande.
- Le test d'ordre stable en intégration peut passer sans le départage par `message`, car
  `now()` diffère d'une transaction à l'autre : le départage est prouvé par le test unitaire.
- La contrainte unique du modèle d'echo n'est pas nommée (`unique=True`), alors que la migration
  0001 la nomme `uq_echos_message` : à aligner avant que les services métier copient le modèle.
