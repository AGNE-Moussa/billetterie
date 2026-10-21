# Scénarios de panne de l'infrastructure (BIL-F16)

Démarche du chaos engineering : on définit l'**état stable**, on pose une **hypothèse**, on
provoque la panne **pendant le trafic**, puis on **observe**. Un écart n'est pas un échec de
l'expérience : c'est une découverte, corrigée avant d'y poser du métier.

- **État stable** : 100 % des appels client réussissent. Newman rejoue `postman/infra.json`
  (créer puis relire un echo par la gateway, avec un jeton du client `services`), 150 fois,
  soit 301 appels en environ 40 s.
- **Rejouer** (aussi en démo) : `make observabilite`, ouvrir http://127.0.0.1:3000, puis
  `make pannes` (les trois scénarios) ou `bash scripts/pannes.sh echo|rabbitmq|consul`. Journaux
  bruts de Newman : `postman/resultats/`.

## Résumé

| Scénario | Avant correctif | Après correctif |
|---|---|---|
| 1. Instance echo tuée net | 5 × 502 sur 301 appels | 0 erreur sur 301 appels |
| 2. RabbitMQ arrêté | 0 erreur, événements partis au retour | inchangé |
| 3. Consul arrêté puis relancé | 38 × 404 sur 301 appels, au retour de Consul | 0 erreur sur 301 appels |

Mesures du 2026-10-21, plateforme locale (deux instances d'echo).

## Scénario 1 : une instance d'echo tombe

- **Panne** : `docker compose kill echo-1` (SIGKILL : l'instance ne se retire pas de Consul),
  15 s, puis relance.
- **Hypothèse** : echo-2 prend tout le trafic ; le client ne voit aucune erreur.
- **Observé avant correctif** : 5 × 502. Traefik route encore vers echo-1 jusqu'à ce que son
  check Consul échoue (intervalle de 10 s) : les connexions vers l'instance morte sont refusées.
- **Correctif** : middleware `nouvelles-tentatives` (retry, 3 tentatives, 100 ms) en fin des
  chaînes `standard` et `partenaires` (`infra/traefik/dynamique.yml`). Une erreur réseau est
  rejouée vers une autre instance.
- **Observé après correctif** : 0 erreur (151 × 200, 150 × 201).
- **Dans Grafana** : « Instances mesurées » passe echo-1 en panne puis en marche ; « Débit par
  service » reste stable ; « Gateway : réponses par code » ne montre aucun 502 ; Prometheus
  compte plus de requêtes sur echo-2 que sur echo-1 sur la période.
- **Limite connue** : seules les erreurs réseau sont rejouées. Une instance qui meurt *après*
  avoir traité un POST et *avant* d'avoir répondu voit ce POST rejoué ailleurs : 409 pour echo
  (message unique), doublon possible pour une route sans contrainte d'unicité. Les routes
  métier non idempotentes devront s'appuyer sur `Idempotency-Key` (BIL-F12).

## Scénario 2 : RabbitMQ s'arrête

- **Panne** : `docker compose stop rabbitmq`, 15 s, puis relance.
- **Hypothèse** : les écritures réussissent (201) ; les événements attendent dans l'outbox et
  partent au retour du broker (BIL-F14).
- **Observé** : 0 erreur côté client ; 60 à 63 événements en attente dans l'outbox pendant la
  panne, tous publiés moins de 10 s après le retour du broker. Hypothèse confirmée.
- **Dans Grafana** : « Débit » et « Erreurs 5xx » d'echo inchangés ; « Files RabbitMQ » sans
  données pendant la panne (le broker n'est plus mesuré), puis de retour. Les journaux d'echo
  signalent la panne une fois au début (« Publication impossible ») et une fois à la fin
  (« Publication rétablie »).

## Scénario 3 : Consul s'arrête

- **Panne** : `docker compose stop consul`, 15 s, puis relance.
- **Hypothèse** : Traefik garde les dernières routes connues ; le client ne voit aucune erreur ;
  au retour de Consul, les instances y figurent toujours.
- **Observé avant correctif** : aucune erreur *pendant* la panne (Traefik journalise des erreurs
  de provider mais garde ses routes), puis 38 × 404 *au retour* de Consul. L'agent restaure les
  instances de son état local, mais avec des checks « critical » jusqu'au premier check réussi :
  Traefik (`strictChecks: passing`) n'a plus aucune instance d'echo pendant 5 à 6 s.
- **Correctif** : les checks sont déclarés avec l'état initial `passing` (`commun.registre`,
  `infra/consul/keycloak.json`). L'inscription a lieu en fin de démarrage, quand l'instance est
  prête ; une instance malade est retirée dès son premier check.
- **Observé après correctif** : 0 erreur ; echo-1 et echo-2 présentes dans Consul après son
  retour.
- **Dans Grafana** : les instances d'echo restent « en marche » (Prometheus découvre ses cibles
  dans Consul : pendant la panne, il garde les dernières cibles connues).
- **Limite connue** : Consul tourne en mode dev. Un conteneur Consul *recréé* (et non redémarré)
  repart vide : les instances n'y reviennent qu'à leur propre redémarrage. Un Consul persistant
  (mode serveur avec volume) ou une réinscription périodique par les services lèveront cette
  limite avant l'environnement de démo (BIL-F29).
