# Conception de la billetterie

Copie versionnée de la page Notion « Billetterie en ligne » (sections Vision, Microservices,
Règles métier, Flux critique, Pannes et API partenaires). La page Notion reste la source :
toute modification de la conception s'y fait d'abord, puis est reportée ici.

## Vision et défi technique

Une plateforme de vente de billets pour concerts et spectacles, ouverte au public et à des
revendeurs partenaires.

**Défi propre : vendre un stock limité sous une charge extrême.** À l'ouverture des ventes, des
milliers de clients visent les mêmes places en même temps. Aucune place ne doit être vendue deux
fois, et le site doit rester utilisable pendant le pic.

Ce que le projet démontre : verrou court sur une place (Redis), contrôle de concurrence en base,
file d'attente virtuelle à l'ouverture des ventes, mise à l'échelle des services Billets et
Commandes.

## Microservices et données

| Service | Responsabilité | Données propres | Instances | Lot |
|---|---|---|---|---|
| Catalogue | Événements, lieux, séances, catégories, recherche | Événements, lieux, plans de salle | 1 | MVP |
| Billets | Stock de places, verrou temporaire, émission des billets avec QR code | Places, billets | 2 | MVP |
| Commandes | Panier, création et suivi de commande, expiration | Commandes, lignes | 2 | MVP |
| Paiements | Paiement simulé en mode test, remboursement | Transactions | 1 | MVP |
| Notifications | E-mails de confirmation, d'annulation et de rappel | Historique d'envoi | 1 | MVP |
| File d'attente | Salle d'attente virtuelle à l'ouverture d'une vente | Positions (Redis) | 1 | V2 |

Les comptes utilisateurs sont gérés par Keycloak (realm `billetterie`) ; aucun service
Utilisateurs dédié n'est nécessaire au MVP.

## Règles métier

1. Une place sélectionnée est verrouillée pour une durée limitée (valeur à fixer, par exemple
   10 minutes), puis libérée automatiquement si la commande n'est pas payée.
2. Une place ne peut jamais être vendue deux fois : le verrou Redis évite la plupart des
   conflits, une contrainte unique en base garantit le reste.
3. Un client ne peut pas dépasser un nombre maximal de billets par séance.
4. Un billet n'est émis qu'après confirmation du paiement.
5. L'annulation d'une séance rembourse automatiquement toutes ses commandes.
6. Un revendeur partenaire voit le catalogue et ses propres commandes, jamais celles des autres.

## Flux critique et événements

Préalable : à la création d'une séance, Catalogue publie `ticketing.show.scheduled` ; Billets crée
alors les places de la séance (asynchrone).

Parcours d'achat d'un billet :

1. Le client choisit ses places ; Commandes crée la commande en attente, puis demande à Billets
   de verrouiller chaque place pour 10 minutes (synchrone).
2. Billets pose le verrou Redis et répond ; refus immédiat si la place est déjà prise (la
   commande expire et libère les places déjà verrouillées).
3. Juste avant de payer, Commandes reverrouille ses places pour 1 heure (une place perdue :
   commande expirée, aucun débit), puis appelle Paiements (synchrone).
4. Paiement accepté : Commandes publie `ticketing.order.confirmed`.
5. Billets émet le billet ; Notifications envoie l'e-mail (asynchrone). Si la place a quand même
   été vendue entre-temps (ou la séance annulée), Billets n'émet aucun billet et publie
   `ticketing.ticket.rejected` : la commande est remboursée.
6. Paiement refusé ou délai dépassé : `ticketing.order.expired`, la place est libérée.

| Événement | Émetteur | Consommateurs |
|---|---|---|
| `ticketing.order.confirmed` | Commandes | Billets, Notifications |
| `ticketing.order.expired` | Commandes | Billets |
| `ticketing.ticket.issued` | Billets | Notifications |
| `ticketing.ticket.rejected` | Billets | Paiements, Notifications |
| `ticketing.show.scheduled` | Catalogue | Billets, Notifications |
| `ticketing.show.cancelled` | Catalogue | Billets, Commandes, Paiements, Notifications |
| `ticketing.payment.refunded` | Paiements | Commandes, Notifications |

## Gestion des pannes

| Service en panne | Comportement | Réponse au client |
|---|---|---|
| Notifications | Messages conservés dans RabbitMQ, envoyés au redémarrage | Achat confirmé normalement |
| Catalogue | Lecture depuis le cache Redis | 200 avec données en cache, sinon 503 |
| Paiements | Commande en attente, place verrouillée jusqu'à expiration | 503 avec invitation à réessayer |
| Billets (une instance) | L'autre instance prend le relais via le load balancing | Aucun impact visible |
| Billets (toutes) | Achat impossible, consultation possible | 503 explicite sur l'achat |

Scénario de démonstration : arrêter une instance de Billets pendant une rafale d'achats, montrer
que les commandes passent toujours, puis arrêter Notifications et montrer que les e-mails partent
au redémarrage.

## API partenaires et lots

Les revendeurs partenaires utilisent le flux Client Credentials avec les scopes `events:read`,
`orders:read`, `orders:write` et `tickets:read`. Routes exposées : liste et détail des
événements, disponibilité des places, création et suivi de commandes et lecture des billets pour
leur propre compte.

- **MVP** : Catalogue, Billets, Commandes, Paiements simulés, Notifications, verrou des places,
  scénario de panne
- **V2** : file d'attente virtuelle, plan de salle interactif, test de charge (k6 ou Gatling)
  pour mesurer le comportement au pic
- **V3** : revente entre particuliers, contrôle d'accès par scan du QR code
