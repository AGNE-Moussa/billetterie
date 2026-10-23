---
name: write-tests
description: "Étape « tests » du pipeline (docs/workflow.md) : répartit les cas du plan validé docs/test-plans/<ID>.md entre unit-test-writer (unitaire, composant) et integration-test-writer (intégration, parcours), lancés en parallèle, puis vérifie que les nouveaux tests sont rouges pour la bonne raison. Appelé par /ticket après le squelette."
argument-hint: "<Ticket ID, par exemple BIL-006>"
---
Tu fais écrire les tests rouges du ticket **$ARGUMENTS**. Tu n'écris aucun test toi-même : ce
sont les agents qui écrivent, toi tu répartis et tu vérifies.

## 1. Le plan doit être validé

Lis `docs/test-plans/$ARGUMENTS.md`. Si la section « Questions » contient encore une question
sans réponse, **arrête-toi** : un plan n'est validé que lorsque le développeur a répondu à
toutes les questions (validation 1). Liste les questions ouvertes et rends la main.

Vérifie aussi que le squelette existe (étape `squelette` faite) : sinon, arrête-toi et dis-le.

## 2. Répartir

Écris `tests` dans `.pipeline/etape` (crée le dossier `.pipeline/` si besoin) et relis le fichier :
si l'écriture a échoué, **arrête-toi**, les tests resteraient verrouillés. Compte les cas du plan
par niveau :

| Niveaux | Agent |
|---|---|
| `unitaire`, `composant` | `unit-test-writer` |
| `intégration`, `parcours` | `integration-test-writer` |

Lance les agents nécessaires **en parallèle, dans le même message** (deux appels d'agent
simultanés). Un agent dont aucun niveau n'apparaît dans le plan **n'est pas lancé**. Donne à
chacun l'ID du ticket et la liste des cas qui le concernent.

## 3. Vérifier le rouge

**Aucun résultat sans mesure.** Si un agent rapporte qu'il n'a rien écrit (écriture refusée,
information manquante), recopie son rapport et arrête-toi : il n'y a rien à vérifier. Ne rends
jamais un tableau de résultats que tu n'as pas obtenus toi-même par la commande ci-dessous ; cite
sa dernière ligne (`N failed, M passed`).

Repère les fichiers de tests créés ou modifiés (`git status --short`) et lance-les :
`uv run pytest <fichiers> -q -p no:cacheprovider` (front : `npm --prefix frontend run test --
--run`, et Playwright si la plateforme tourne). Classe chaque test :

- **rouge, assertion** (`assert 501 == 204`, élément introuvable) : attendu ;
- **vert par le squelette** : une garde du contrat (401, 403, 422) ou la forme d'un schéma du
  contrat (champs d'un modèle de réponse) posées par le squelette : admis, à lister ;
- **erreur** (`ERROR collecting`, `ImportError`, `NameError`, fixture introuvable, erreur
  TypeScript) ou **vert sans raison** : renvoie l'agent concerné corriger son test, une fois ;
  s'il échoue encore, arrête-toi et signale-le.

Rends un tableau : cas du plan, fichier, résultat, raison. Les cas que les agents n'ont pas
écrits faute d'information (règle « rien d'inventé ») sont listés à part.
