# BIL-F16 : Scénarios de panne de l'infrastructure

- **Branche** : `test/bil-f16-pannes-infra`
- **Dépend de** : BIL-F12, BIL-F14, BIL-F15

## Objectif

Prouver que l'infrastructure encaisse les pannes avant d'y poser du métier.

## Étapes

- [x] 1. `scripts/pannes.sh` : instance echo tuée, RabbitMQ arrêté, Consul arrêté, puis
  redémarrage (`make pannes` pour les trois)
- [x] 2. Pour chaque scénario : hypothèse, résultat observé (Newman, Prometheus, Grafana),
  résultat attendu
- [x] 3. Collection `postman/infra.json` rejouée par Newman (image Docker
  `postman/newman:6.1.3-alpine`, sur le réseau `billetterie`) pendant les pannes
- [x] 4. Résultats consignés dans `docs/pannes-infra.md`

## Critères d'acceptance

- [x] CA1 : une instance d'echo arrêtée, aucune erreur visible côté client (après correctif :
  301 appels sur 301 réussis, l'instance étant tuée net)
- [x] CA2 : RabbitMQ arrêté, les événements partent à son retour (60 à 63 événements en attente,
  publiés moins de 10 s après le retour)
- [x] CA3 : chaque scénario est documenté avec hypothèse et résultat (avant et après correctif)

## Contraintes

- Scénarios rejouables en direct pendant une démo : une commande, étapes horodatées et commentées
  à l'écran, bilan côté client.

## Découvertes et correctifs (validés par le développeur)

- Instance tuée net : 5 × 502. Middleware Traefik `nouvelles-tentatives` (retry sur erreur
  réseau) dans les chaînes `standard` et `partenaires`.
- Consul relancé : 38 × 404, checks restaurés « critical ». Checks déclarés `passing` à
  l'inscription (`commun.registre`, `infra/consul/keycloak.json`).

## Limites consignées

- Un POST traité par une instance qui meurt avant de répondre peut être rejoué ailleurs.
- Consul en mode dev : un conteneur recréé repart vide (à traiter avant BIL-F29).
