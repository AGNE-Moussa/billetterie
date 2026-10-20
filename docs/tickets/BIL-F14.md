# BIL-F14 : Code commun : outbox, FastStream et consommateurs idempotents

- **Branche** : `feat/bil-f14-outbox-faststream`
- **Dépend de** : BIL-F11

## Objectif

Garantir qu'aucun événement n'est perdu après une écriture en base, et qu'un message reçu deux
fois n'est traité qu'une fois.

## Étapes

- [x] 1. Enveloppe d'événement `commun.evenements.Evenement` : `id`, `type`
  (`ticketing.<entité>.<fait>`, validé), `version`, `occurred_at`, `correlation_id`, `data`
- [x] 2. Tables `outbox` et `messages_traites` (`commun.outbox`, migration type
  `services/echo/alembic/versions/0002_creer_tables_messagerie.py`) ; `publier_plus_tard(session,
  evenement)` dans la même transaction que l'écriture métier
- [x] 3. `RelaisOutbox` : lit l'outbox (`FOR UPDATE SKIP LOCKED`), publie sur l'exchange topic
  `ticketing` avec confirmation du broker, puis marque la ligne envoyée
- [x] 4. `consommateur_idempotent` : table `messages_traites`, quorum queue avec
  `x-delivery-limit`, DLQ `<nom>.dlq` par l'exchange `ticketing.dlx`, trois tentatives avant DLQ
- [x] 5. Tests d'intégration Testcontainers (PostgreSQL et RabbitMQ) :
  `tests/integration/test_messagerie.py`

## Critères d'acceptance

- [x] CA1 : broker arrêté pendant l'écriture, l'événement part au redémarrage (test d'intégration ;
  plateforme locale : POST d'echo à 201 pendant l'arrêt de RabbitMQ, événement reçu au retour)
- [x] CA2 : un message livré deux fois ne produit qu'un seul effet
- [x] CA3 : un message en échec répété arrive dans la DLQ (après exactement trois tentatives,
  chaque échec annulé)

## Contraintes

- Aucune publication directe sur RabbitMQ depuis le code métier : toujours via l'outbox.

## Décisions (validées par le développeur)

- Relais en tâche de fond du lifespan de chaque instance, `SKIP LOCKED` entre instances.
- Tentatives comptées par RabbitMQ (quorum queue, `x-delivery-limit` = tentatives - 1).
- Echo : publication de `ticketing.echo.created` seulement ; le consommateur est démontré dans
  les tests d'intégration.

## Choix techniques

- Le relais gère lui-même la connexion au broker : un service démarre et écrit sans RabbitMQ.
  Une panne est journalisée à son début et à sa fin, pas à chaque passe.
- Les files d'erreur sont déclarées avant le démarrage des consommateurs (`messagerie(broker)`) :
  un message envoyé vers une file absente serait perdu.

## Corrigé au passage

- `alembic/env.py` d'echo : `fileConfig(..., disable_existing_loggers=False)`. Sinon, les
  migrations lancées dans le même processus (tests) coupaient les journaux déjà créés.
