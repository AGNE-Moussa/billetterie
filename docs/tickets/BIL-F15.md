# BIL-F15 : Observabilité : OpenTelemetry, Prometheus, Grafana

- **Branche** : `feat/bil-f15-observabilite`
- **Dépend de** : BIL-F08

## Objectif

Rendre visibles métriques et traces de tous les services dans un tableau de bord Grafana prêt
pour la démo.

## Étapes

- [x] 1. `libs/commun/observabilite.py` : `installer_observabilite(app, service)` (traces
  FastAPI et httpx, export OTLP, `/metrics`) et `instrumenter_moteur(moteur)` (requêtes SQL)
- [x] 2. `/metrics` sur chaque service ; Prometheus découvre les cibles via Consul (métadonnée
  `metriques` posée par `commun.registre`)
- [x] 3. Grafana provisionné (`infra/grafana`) : débit, latence p95, erreurs par service, réponses
  de la gateway, état des disjoncteurs, profondeur des files RabbitMQ, instances, dernières traces
- [x] 4. Traces dans Tempo, choix documenté dans `docs/adr/002-traces-tempo.md`

## Critères d'acceptance

- [x] CA1 : le tableau de bord affiche le trafic de `services/echo` sans configuration manuelle
  (plateforme locale : les deux instances découvertes dans Consul, panneau « Débit » renseigné)
- [x] CA2 : une requête est suivie dans les traces de la gateway jusqu'à la base (plateforme
  locale : trace Traefik → vérificateur → echo → `SELECT` ; tests unitaires de la reprise du
  `traceparent` et des spans SQL)

## Contraintes

- Profil Compose `observabilite` pour Prometheus et Grafana (`make observabilite`).

## Décisions (validées par le développeur)

- Tempo, consulté dans Grafana (ADR-002).
- Tempo démarre toujours (léger) : Traefik exporte ses traces sans erreur même hors profil.
- L'instrumentation SQLAlchemy d'OpenTelemetry se déclare limitée à SQLAlchemy < 2.1 : elle est
  forcée (`skip_dep_check`), et un test unitaire prouve que les spans SQL existent.

## Choix techniques

- `/health` et `/metrics` ne sont ni tracés ni comptés.
- Les journaux JSON portent `trace_id` : une ligne de journal mène à sa trace.
- Le vérificateur est instrumenté aussi : l'appel ForwardAuth apparaît dans la trace.
