# BIL-F05 : Compose de base (PostgreSQL, Redis, RabbitMQ)

- **Branche** : `feat/bil-f05-compose-base`
- **Dépend de** : BIL-F04

## Objectif

Lancer en une commande les briques de données du projet : PostgreSQL (une base par service),
Redis et RabbitMQ.

## Étapes

- [x] 1. `compose.yaml` avec PostgreSQL 16, Redis 7, RabbitMQ 3 (plugin management), Mailpit
- [x] 2. Script d'initialisation qui crée les bases `catalogue`, `billets`, `commandes`,
  `paiements`, `notifications`, chacune avec son utilisateur
- [x] 3. Healthchecks sur chaque conteneur ; réseau `billetterie`
- [x] 4. Variables lues depuis `.env` (copié de `.env.example`)

## Critères d'acceptance

- [x] CA1 : `make up` démarre tous les conteneurs en état healthy
- [x] CA2 : les cinq bases existent avec des utilisateurs distincts (`billets` refusé sur `commandes`)
- [x] CA3 : l'interface RabbitMQ (`127.0.0.1:15672`) et Mailpit (`127.0.0.1:8025`) sont accessibles

## Contraintes

- Images avec version figée, compatibles ARM64 (démo sur VPS ARM) : vérifié avec
  `docker buildx imagetools inspect`.
