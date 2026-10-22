# BIL-F21 : Workflow : agents unit-test-writer et integration-test-writer

- **Branche** : `chore/bil-f21-test-writers`
- **Dépend de** : BIL-F20

## Objectif

Créer les deux agents qui écrivent les tests rouges à partir du plan validé, chacun dans son
dossier.

## Étapes

- [x] 1. `unit-test-writer.md` : cas `unitaire` et `composant`, dossiers de tests unitaires et
  `frontend/src/**/*.test.tsx` ; pas de Docker
- [x] 2. `integration-test-writer.md` : cas `intégration` et `parcours`, dossiers de tests
  d'intégration et de contrat, `frontend/e2e/` ; Docker autorisé
- [x] 3. Les deux lancent leurs tests et vérifient qu'ils échouent sur une assertion
- [x] 4. Concurrence : vraies requêtes parallèles (`asyncio.gather`) sur la même place

## Critères d'acceptance (vérifiés par des sessions `claude -p` réelles)

- [x] CA1 : chaque agent ne peut écrire que dans ses dossiers (hook d'agent
  `limiter_ecriture.py`, motif `**`) et ne lance que les commandes de sa liste blanche
  (`limiter_commandes.py` : pas de Docker pour l'unitaire, pas de redirection) ;
  `tests/unit/test_agents_claude.py`
- [x] CA2 : ticket d'essai « supprimer un echo » (contrat, plan, squelette, puis les deux agents
  en parallèle) : les 6 tests rouges échouent tous sur une assertion (`assert 501 == 204` ×4,
  `assert 501 == 404` ×2), aucune `ImportError` ni erreur de collecte. Côté front, l'exécution
  est un critère ajouté à BIL-F26.
- [x] CA3 : ticket front d'essai entièrement spécifié : `unit-test-writer` produit un test
  Vitest et Testing Library, `integration-test-writer` un test Playwright, sélecteurs par rôle

Les fichiers des essais ne sont pas commités.

## Contraintes

- Données de test synthétiques uniquement.

## Décisions (validées par le développeur)

- Étape « squelette » par `implementer` juste après la validation 1 (marqueur `squelette`, tests
  verrouillés) : routes du contrat en 501, fonctions du domaine vides ; les tests échouent sur
  une assertion, pas sur une `ImportError`. Ajouté au périmètre de BIL-F22.
- Un test vert dès le squelette est permis s'il ne vérifie qu'une garde du contrat (401, 403,
  422), et il est signalé à part.
- Rien d'inventé : un cas bloqué par une question ouverte n'est pas écrit, il est listé ;
  `/write-tests` refusera un plan qui a encore des questions.
- Exécution des tests front reportée à BIL-F26 (critère ajouté).

## Correctif au passage

- Hook Stop : à l'étape `tests`, les tests rouges sont attendus, il ne les lance plus.
