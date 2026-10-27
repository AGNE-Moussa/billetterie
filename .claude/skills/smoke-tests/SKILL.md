---
name: smoke-tests
description: "Hors pipeline : écrit ou complète les smoke tests de tests/smoke/ quand une user story ajoute un parcours critique de bout en bout (achat complet d'un billet, parcours revendeur), joués contre la plateforme lancée par make up. Les tests Playwright d'un écran restent dans le pipeline du ticket (frontend/e2e/)."
argument-hint: "<parcours, par exemple « achat complet d'un billet »>"
---
Tu complètes les smoke tests de la plateforme pour le parcours : **$ARGUMENTS**. Les smoke tests
vérifient que la plateforme **complète** répond, de bout en bout ; ils ne remplacent ni les tests
d'un ticket ni les tests Playwright d'un écran (`frontend/e2e/`, dans le pipeline).

## Quand

Seulement quand une user story ajoute ou change un parcours critique : services sains,
connexion, achat complet d'un billet, parcours revendeur. Sinon, dis-le et ne fais rien.

## Comment

- Fichiers `tests/smoke/test_<parcours>.py`, marqués `pytestmark = pytest.mark.smoke` : ils ne
  tournent ni avec `make test` ni en CI d'une PR, seulement avec `make test-smoke`.
- Contre la plateforme réelle : `make up` (ou `make observabilite`), gateway sur
  `http://localhost`. Si la gateway ne répond pas, le test est **ignoré** (`pytest.skip`) avec
  un message clair, il n'échoue pas.
- Jetons réels du realm : clients `services` et `revendeur-test` (Client Credentials) ou
  utilisateurs de test (`client.test`, `admin.test`), secrets lus dans `.env`, jamais écrits
  dans le test.
- Un test par parcours, qui enchaîne les appels comme un vrai client et vérifie chaque étape
  (statuts, corps Problem Details, événements arrivés quand c'est observable).
- Données synthétiques, créées par le test lui-même ; rejouable plusieurs fois de suite.

Lance `make test-smoke` sur la plateforme démarrée et rends le résultat. Ces tests sont rejoués
avant chaque démo, juste avant les scénarios de panne (`make pannes`).
