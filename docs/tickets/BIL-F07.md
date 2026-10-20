# BIL-F07 : API Gateway Traefik (routage, load balancing, limitation de débit)

- **Branche** : `feat/bil-f07-traefik`
- **Dépend de** : BIL-F06

## Objectif

Faire de Traefik le point d'entrée unique, qui découvre les services dans Consul et répartit les
appels entre les instances saines.

## Étapes

- [x] 1. Conteneur Traefik v3, fournisseur Consul Catalog, `exposedByDefault=false`
- [x] 2. Convention de tags : chaque service déclare sa règle `PathPrefix(/api/v1/<ressource>)`
  dans ses tags Consul (`commun.registre.tags_traefik`)
- [x] 3. Middlewares : limitation de débit (générale et stricte pour les partenaires), CORS
  (origines par variable), en-tête `X-Correlation-Id` créé s'il est absent
- [x] 4. Tableau de bord Traefik accessible en local seulement

## Critères d'acceptance

- [x] CA1 : deux instances d'un même service reçoivent chacune une part des appels
- [x] CA2 : une instance retirée de Consul ne reçoit plus d'appel
- [x] CA3 : au-delà de la limite, la gateway répond 429 (limite partenaires et limite générale)

## Contraintes

- Configuration dynamique uniquement par tags Consul, aucune route écrite en dur.
