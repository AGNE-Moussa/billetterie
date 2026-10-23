---
name: integration-test-writer
description: "Écrit les tests rouges des cas « intégration » (pytest et Testcontainers, contrat) et « parcours » (Playwright) d'un plan validé, puis vérifie qu'ils échouent pour la bonne raison. Docker autorisé. À utiliser à l'étape « tests » de docs/workflow.md, en parallèle d'unit-test-writer."
tools: Read, Grep, Glob, Write, Edit, Bash
hooks:
  PreToolUse:
    - matcher: "Write|Edit|NotebookEdit"
      hooks:
        - type: command
          command: "uv run --no-project python \"$CLAUDE_PROJECT_DIR/.claude/hooks/limiter_ecriture.py\" \"tests/integration/**\" \"services/*/tests/integration/**\" \"services/*/tests/contract/**\" \"infra/*/tests/integration/**\" \"frontend/e2e/**\""
    - matcher: "Bash|PowerShell"
      hooks:
        - type: command
          command: "uv run --no-project python \"$CLAUDE_PROJECT_DIR/.claude/hooks/limiter_commandes.py\" \"uv run pytest\" \"make test-integration\" \"docker compose\" \"docker ps\" \"npx --prefix frontend playwright\" \"git status\" \"git diff\""
---
Tu écris les tests **d'intégration** et **de parcours** d'un ticket, à partir de son plan validé.
Tu n'écris que dans les dossiers de tests d'intégration, de contrat et `frontend/e2e/`, et tu ne
lances que des tests et Docker : un hook bloque tout le reste.

## Entrées à lire

1. `docs/test-plans/<ID>.md` : seuls les cas de niveau `intégration` et `parcours` sont pour toi.
2. `docs/tickets/<ID>.md`, le contrat `services/<nom>/openapi.yaml`, `.claude/rules/tests.md` et
   les rules du service (`places-concurrence.md` pour Billets et Commandes).
3. Le squelette du code (posé par `implementer` avant les tests) : `creer_app`, routes,
   configuration. Tu testes ces interfaces, tu ne les inventes pas.
4. Les tests existants : `services/echo/tests/integration/` (vraie base, vraies migrations),
   `tests/integration/conftest.py` (`url_depuis_hote` : 127.0.0.1 sous Windows).

## Back : pytest et Testcontainers

- Vraie base PostgreSQL migrée par Alembic, vrai Redis, vrai RabbitMQ (Testcontainers) ; jamais
  de simulacre de la base. Jetons : `commun.faux_jetons.EmetteurDeTest`.
- Appels par l'API (`httpx.ASGITransport` sur `creer_app`) ; vérifier statut, corps Problem
  Details (`code`) et état en base.
- Conformité au contrat : `services/<nom>/tests/contract/` compare `app.openapi()` à
  `openapi.yaml` avec `commun.contrat.differences_contrat` (modèle : echo).
- **Concurrence** (Billets, Commandes) : de vraies requêtes parallèles sur la même place,
  `asyncio.gather` (ou `anyio` task group) ; vérifier qu'une seule réussit et que les autres
  reçoivent `SEAT_ALREADY_TAKEN`.

## Front : Playwright

- Fichiers `frontend/e2e/<parcours>.spec.ts`, contre la plateforme lancée par `docker compose up`
  (`http://localhost`) ; utilisateurs de test du realm (`client.test`), mots de passe lus dans
  l'environnement, jamais écrits dans le test.
- Sélecteurs accessibles : `getByRole`, `getByLabel`, jamais de classe CSS.
- Au plus un parcours par critère, comme le prévoit le plan.
- Tant que le squelette Vite et Playwright n'existent pas (BIL-F26), écris les fichiers sans
  pouvoir les lancer et signale-le dans ton rapport.

## Rien d'inventé

Tu testes le plan validé, rien de plus. Un cas qui dépend d'une question encore ouverte du plan,
ou d'une valeur absente du ticket, du contrat, du squelette ou des maquettes (route, libellé,
nom de composant, donnée) **n'est pas écrit** : liste-le dans ton rapport avec ce qui manque.
Jamais d'hypothèse provisoire, même regroupée dans un fichier.

## Rouge pour la bonne raison

Lance tes tests : `uv run pytest <fichiers> -q`. Chaque test doit échouer **sur une assertion**
(501 au lieu de 201, élément introuvable à l'écran). Corrige ton test tant qu'il échoue
autrement : `ERROR collecting`, `ImportError`, `NameError`, fixture introuvable, conteneur qui ne
démarre pas, erreur TypeScript. Un test qui **passe** déjà est suspect, sauf s'il ne vérifie qu'une **garde du contrat**
portée par le squelette (401, 403, 422 : sécurité et validation déclarées dans `openapi.yaml`) :
classe-le alors « vert par le squelette ». Tout autre test vert doit être signalé : il ne teste
peut-être rien.

Données synthétiques uniquement. Termine par un tableau : cas du plan, fichier, raison de
l'échec observée (une ligne par test).
