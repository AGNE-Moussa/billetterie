# Conventions

Copie versionnée de la section Conventions de la page Notion « Billetterie en ligne ». Ces règles
donnent aux agents IA un cadre stable ; elles sont déclinées en rules dans `.claude/rules/`
(BIL-F18).

- **Contrat d'abord** : chaque service a un fichier OpenAPI 3.1 écrit avant le code. Un test en
  CI compare le schéma généré par FastAPI au contrat validé.
- **Routes** : `/api/v1/<ressource>` en pluriel, verbes HTTP standards, pagination
  `?page=&size=`.
- **Erreurs** : Problem Details (RFC 9457) avec un code métier stable, par exemple
  `SEAT_ALREADY_TAKEN`.
- **Données** : une base par service, aucune jointure entre services ; on référence un objet d'un
  autre service par son UUID ; montants en centimes.
- **Événements** : nom au passé `ticketing.<entité>.<fait>` ; charge utile versionnée ;
  consommateurs idempotents.
- **Cohérence** : publication via une table outbox, jamais directement.
- **Traçabilité** : identifiant de corrélation créé par la gateway, propagé dans les appels et
  les messages, présent dans chaque ligne de journal.
- **Santé** : `/health` sur chaque service, utilisé par Consul.
- **Configuration** : variables d'environnement uniquement, aucun secret dans le dépôt.
