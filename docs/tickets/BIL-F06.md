# BIL-F06 : Registre Consul et health checks

- **Branche** : `feat/bil-f06-consul`
- **Dépend de** : BIL-F05

## Objectif

Ajouter Consul comme registre de services, avec retrait automatique des instances malades.

## Étapes

- [x] 1. Conteneur Consul (un nœud serveur) dans le compose, interface web exposée en local seulement
- [x] 2. `libs/commun/registre.py` : enregistrement au démarrage avec adresse, port, check HTTP
  sur `/health` toutes les 10 s et `DeregisterCriticalServiceAfter` à 1 min
- [x] 3. Désenregistrement propre à l'arrêt (lifespan FastAPI)
- [x] 4. Test d'intégration avec Testcontainers : un faux service s'enregistre puis disparaît

## Critères d'acceptance

- [x] CA1 : un service démarré apparaît dans Consul avec un check vert (`test_service_demarre_apparait_avec_check_vert`)
- [x] CA2 : un service arrêté brutalement passe en critique puis est retiré (`test_service_tue_passe_critique_puis_est_retire`, environ 100 s)

## Contraintes

- Adresse de Consul uniquement par variable d'environnement (`CONSUL_URL`).
