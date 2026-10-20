# ADR-002 : Tempo pour les traces distribuées

- **Statut** : acceptée (BIL-F15)
- **Date** : 2026-10-20

## Contexte

Les services et Traefik émettent des traces OpenTelemetry (OTLP). Il faut un backend pour les
stocker et les consulter, en local et pendant la démo de panne, où l'on montre en direct le
trafic, les erreurs et le chemin d'une requête. Deux candidats : Grafana Tempo et Jaeger.

## Décision

**Tempo** (`grafana/tempo`, un seul processus, stockage local éphémère), consulté dans Grafana.

- Les services et Traefik exportent directement en OTLP HTTP vers Tempo, sans collecteur
  OpenTelemetry intermédiaire (un composant de moins ; à ajouter si l'on doit filtrer,
  échantillonner ou exporter vers plusieurs destinations).
- Tempo démarre toujours avec `make up` (il est léger) : Traefik, qui ne lit qu'un fichier de
  configuration statique, exporte ainsi sans erreur. Prometheus et Grafana restent dans le profil
  Compose `observabilite`.

## Raisons

- **Un seul écran pour la démo** : métriques (Prometheus) et traces (Tempo) dans le même tableau
  de bord Grafana ; on passe d'un pic de latence ou d'erreurs à la trace concernée sans changer
  d'outil.
- Tempo n'indexe que les identifiants de trace : très peu de ressources, adapté à un poste de
  développement et à un petit VPS.
- Grafana est déjà nécessaire pour les métriques : aucune interface de plus à apprendre.

## Conséquences

- La recherche se fait en TraceQL (`{resource.service.name="echo"}`), moins familière que les
  filtres de l'interface Jaeger.
- Les traces sont perdues à l'arrêt du conteneur (tmpfs) : voulu pour le développement ; un
  volume ou un stockage objet serait nécessaire pour un environnement durable.
- Écarté : **Jaeger** (all-in-one), plus simple à lancer et à l'interface très connue, mais qui
  impose une seconde interface pendant la démo.
