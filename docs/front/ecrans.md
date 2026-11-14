# Écrans du front billetterie

Liste des écrans (BIL-018), avec leurs données, leurs routes d'API et une maquette basse
fidélité : la structure compte, pas le pixel. Parcours : `parcours.md` ; routes React :
`routes.md`.

## Règles communes

- Chaque écran est rendu dans le `<main>` de `MiseEnPage` (en-tête, navigation, pied de page) ;
  les maquettes ne montrent que ce `<main>`.
- États : chargement `Chargement`, vide `Vide`, erreur `Erreur` (titre et détail du Problem
  Details, décision sur `code`), succès. Composants de BIL-F28 (`Carte`, `TableauPagine`,
  `ChampFormulaire`, `Bouton`, `DialogueConfirmation`) ; notifications pour les retours d'action.
- Appels d'API par le client généré (`frontend/src/api/genere/`), jamais de `fetch` écrit main.
- Mode dégradé du catalogue : si la réponse porte `X-Cache-Stale: true`, bandeau « Données
  peut-être pas à jour » au-dessus du contenu (E01, E02, E03).
- Montants en centimes dans l'API, affichés en euros ; dates ISO affichées en heure locale.
- Colonne « Codé » : **oui** si la route existe dans `services/<nom>/openapi.yaml` ; **non** si
  elle n'existe que dans le contrat cible `docs/contrats/` ; **à créer** si elle n'existe nulle
  part (voir les questions Q1 à Q8 en fin de fichier).

## Correspondance

| Écran | Titre | US | Rôle | Ticket front |
| --- | --- | --- | --- | --- |
| E01 | Catalogue des événements | US1 | public | BIL-019 |
| E02 | Fiche événement | US1, US6 | public | BIL-019 |
| E03 | Séance et plan de salle | US1, US2, US5, US6 | public (réserver : `customer`) | BIL-020 |
| E04 | Paiement de la commande | US2, US3, US5 | `customer` | BIL-020, BIL-021 |
| E05 | Suivi d'une commande | US3, US4, US5, US6 | `customer` | BIL-021 |
| E06 | Mes commandes | US3, US5, US6 | `customer` | BIL-021 |
| E07 | Mes billets | US4, US6 | `customer` | BIL-021 |
| E08 | Billet et QR code | US4, US6 | `customer` | BIL-021 |
| E10 | Espace organisateur : événements | US6 | `admin` | BIL-022 |
| E11 | Nouvel événement | US6 | `admin` | BIL-022 |
| E12 | Gérer un événement | US6 | `admin` | BIL-022 |
| E13 | Nouvelle séance | US6 | `admin` | BIL-022 |
| E14 | Séance : remplissage et annulation | US6 | `admin` | BIL-022 |
| E15 | Lieux | US6 | `admin` | BIL-022 |
| E16 | Salle d'attente | US8 | `customer` | BIL-023 (V2) |

US7 (revendeur) : aucun écran, API seule (`docs/contrats/partenaires.yaml`).

Écrans transverses déjà livrés (BIL-F27, BIL-F28) : rappel de connexion
(`PageRappelConnexion`), accès refusé (`PageAccesRefuse`, rendu par `GardeRoles`), page
introuvable (`PageIntrouvable`).

---

## E01 Catalogue des événements

- **Objectif** : trouver un spectacle ; page d'accueil et vitrine.
- **US** : US1. **Rôle** : public.
- **Données** : nom et début de description de chaque événement, pagination ; filtres `q`
  (texte), `ville`, `du`, `au`, reflétés dans l'URL (lien partageable, CA1 de BIL-019).

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/events?q=&ville=&du=&au=&page=&size=` | `listerEvenements` | oui |

- **Chargement** : liste en `Chargement`, filtres déjà utilisables.
- **Vide** : « Aucun événement ne correspond à ces filtres », action « Effacer les filtres ».
- **Erreur** : 422 `REQUETE_INVALIDE` (ex. `du` après `au`) affichée sous les filtres ;
  503 `BASE_INDISPONIBLE` en `Erreur` avec « Réessayer ».

```text
+--------------------------------------------------------------------+
| Événements                                                         |
| [ Rechercher...        ] [ Ville      ] [ du jj/mm ] [ au jj/mm ]  |
| [Filtrer] [Effacer]                                                |
| (bandeau si X-Cache-Stale : données peut-être pas à jour)          |
|                                                                    |
| +-----------------------------+  +-----------------------------+   |
| | Nom de l'événement          |  | Nom de l'événement          |   |
| | Début de la description...  |  | Début de la description...  |   |
| | [Voir les séances]          |  | [Voir les séances]          |   |
| +-----------------------------+  +-----------------------------+   |
|                                                                    |
| < Précédent   Page 1 / 4   Suivant >                               |
+--------------------------------------------------------------------+
```

## E02 Fiche événement

- **Objectif** : voir les séances d'un spectacle et en choisir une.
- **US** : US1 (et US6 : séance annulée signalée). **Rôle** : public.
- **Données** : nom, description ; pour chaque séance : date et heure, lieu (nom, ville),
  catégories et prix (« à partir de »), mention « Annulée » si `annulee`.

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/events/{evenement_id}` | `lireEvenement` | oui |
| GET | `/api/v1/events/{evenement_id}/shows?page=&size=` | `listerSeances` | oui |
| GET | `/api/v1/venues/{lieu_id}` (un appel par lieu distinct, mis en cache) | `lireLieu` | oui |

- **Chargement** : en-tête puis tableau des séances en `Chargement`.
- **Vide** : « Aucune séance programmée pour l'instant », lien retour au catalogue.
- **Erreur** : 404 `EVENT_NOT_FOUND` en page « Événement introuvable » ; 503 en `Erreur`.
- La disponibilité par séance (« Complet », « Places restantes ») n'a pas de route : voir Q4.

```text
+--------------------------------------------------------------------+
| < Retour au catalogue                                              |
| Nom de l'événement                                                 |
| Description complète...                                            |
|                                                                    |
| Séances                                                            |
| +----------------+--------------------+------------+-------------+ |
| | Date           | Lieu               | Prix       |             | |
| +----------------+--------------------+------------+-------------+ |
| | sam. 12/12 20h | Salle X, Lyon      | dès 25 EUR | [Choisir]   | |
| | dim. 13/12 16h | Salle X, Lyon      | dès 25 EUR | Annulée     | |
| +----------------+--------------------+------------+-------------+ |
| < Précédent   Page 1 / 1   Suivant >                               |
+--------------------------------------------------------------------+
```

## E03 Séance et plan de salle

- **Objectif** : voir les places libres et en choisir (10 au plus par commande et par séance).
- **US** : US1 (consulter), US2 (choisir et réserver), US5 (une place abandonnée redevient
  libre au rafraîchissement), US6 (séance annulée : plan en lecture seule).
- **Rôle** : public pour consulter ; « Réserver » exige `customer` (sinon connexion Keycloak,
  retour sur la même URL avec la sélection dans `?places=`).
- **Données** : événement, date, lieu ; légende des catégories (nom, prix) ; grille par rang
  et numéro, chaque place libre, indisponible (`disponible: false`, verrouillée ou vendue, voir
  Q5) ou sélectionnée ; total de la sélection.

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/shows/{seance_id}` | `lireSeanceParId` | oui |
| GET | `/api/v1/events/{evenement_id}` | `lireEvenement` | oui |
| GET | `/api/v1/venues/{lieu_id}` | `lireLieu` | oui |
| GET | `/api/v1/seats?seance_id=&page=&size=100` (toutes les pages) | `listerPlaces` | oui |
| POST | `/api/v1/orders` (réserver, sans `carte_test`, voir Q1) | `creerCommande` | à adapter |

- **Chargement** : en-tête, puis grille en `Chargement`.
- **Vide** : « Les places de cette séance sont en cours de création » (la séance vient d'être
  programmée, création asynchrone), action « Rafraîchir ».
- **Erreur** : 404 `SHOW_NOT_FOUND` en page introuvable ; sur « Réserver » : 409
  `SEAT_ALREADY_TAKEN` (message « Une place vient d'être prise », plan relu, sélection gardée
  sans la place perdue, CA1 de BIL-020), 409 `TICKET_LIMIT_EXCEEDED`, 409 `SHOW_CANCELLED`
  ou `SHOW_ALREADY_STARTED`, 503 `SERVICE_INDISPONIBLE` (« Achat momentanément impossible,
  la consultation reste possible »).
- **Accessibilité** : grille navigable au clavier (flèches), chaque place nommée « Rang B,
  place 12, catégorie Or, 45 euros, libre » (CA2 de BIL-020).

```text
+--------------------------------------------------------------------+
| < Nom de l'événement                                               |
| sam. 12/12 20h - Salle X, Lyon                                     |
| Légende : [ ] libre  [x] indisponible  [#] sélectionnée            |
|           Or 45 EUR   Argent 25 EUR                                |
|                                                                    |
|                         SCÈNE                                      |
|   A  [ ][ ][x][x][ ][ ][ ][ ]      (Or)                            |
|   B  [ ][#][#][ ][x][ ][ ][ ]      (Or)                            |
|   C  [ ][ ][ ][ ][ ][ ][x][ ]      (Argent)                        |
|                                                                    |
| Sélection : B2, B3 - 90 EUR                     (2 places sur 10)  |
| [Réserver ces places]      (non connecté : Se connecter pour       |
|                             réserver)                              |
+--------------------------------------------------------------------+
```

**Variante sans changement du back (si Q1 est refusée)** : « Continuer » mène directement à
E04 avec `?seance=&places=` ; E04 appelle `creerCommande` avec la carte en un seul appel, sans
compte à rebours avant le paiement.

## E04 Paiement de la commande

- **Objectif** : payer une commande réservée avant l'expiration de ses verrous.
- **US** : US2 (compte à rebours), US3 (payer), US5 (expiration).
- **Rôle** : `customer`.
- **Données** : séance (événement, date, lieu), lignes (place, montant), total, compte à
  rebours calculé sur `expire_le` renvoyé par l'API (jamais une horloge arbitraire), champ
  « Numéro de carte de test » (16 chiffres, aucune carte réelle ; rappel des numéros de test).

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/orders/{commande_id}` | `lireCommande` | oui |
| GET | `/api/v1/shows/{seance_id}` | `lireSeanceParId` | oui |
| GET | `/api/v1/events/{evenement_id}` | `lireEvenement` | oui |
| GET | `/api/v1/seats?seance_id=` (libellés rang et numéro, voir Q6) | `listerPlaces` | oui |
| POST | `/api/v1/orders/{commande_id}/payment` | `payerCommande` | oui |

- **Chargement** : récapitulatif en `Chargement` ; pendant le paiement, bouton « Payer »
  désactivé et `aria-busy` (un double clic ne paie qu'une fois, CA1 de BIL-021).
- **Vide** : sans objet (une commande a toujours au moins une ligne).
- **Erreur** : 404 `ORDER_NOT_FOUND` en page introuvable ; commande non `EN_ATTENTE` : renvoi
  vers E05 ; 402 `PAYMENT_REFUSED` (« Paiement refusé, vos places sont libérées », lien vers la
  séance) ; 409 `SEAT_ALREADY_TAKEN`, `SHOW_CANCELLED`, `SHOW_ALREADY_STARTED` (commande
  expirée, aucun débit) ; 409 `REQUEST_IN_PROGRESS` (relire la commande) ; 503 (« Réessayez
  avant hh:mm », bouton toujours actif) ; compte à rebours à zéro : message US5 et lien vers
  la séance.

```text
+--------------------------------------------------------------------+
| Paiement                                                           |
| Nom de l'événement - sam. 12/12 20h - Salle X, Lyon                |
|                                                                    |
| Places réservées pour vous encore  09:42   (role="timer")          |
|                                                                    |
| +---------------------------+-----------+                          |
| | Rang B, place 2 (Or)      |    45 EUR |                          |
| | Rang B, place 3 (Or)      |    45 EUR |                          |
| +---------------------------+-----------+                          |
| | Total                     |    90 EUR |                          |
| +---------------------------+-----------+                          |
|                                                                    |
| Numéro de carte de test  [________________]                        |
| (paiement simulé : 4000000000000002 est refusé)                    |
|                                                                    |
| [Payer 90 EUR]                         [Abandonner]                |
+--------------------------------------------------------------------+
```

« Abandonner » ne fait que revenir à la séance : aucune route ne libère une commande avant son
expiration (voir Q7).

## E05 Suivi d'une commande

- **Objectif** : voir où en est une commande ; sert de page de confirmation après paiement.
- **US** : US3 (confirmée), US4 (billets émis, e-mail envoyé), US5 (expirée), US6
  (remboursée).
- **Rôle** : `customer`.
- **Données** : statut, séance, lignes, total, date ; selon le statut :
  - `CONFIRMEE` : « Paiement accepté, vos billets arrivent par e-mail », billets de la
    commande (relus toutes les quelques secondes tant qu'ils ne sont pas tous émis) ;
  - `EN_ATTENTE` : compte à rebours et bouton « Payer » vers E04 ;
  - `EXPIREE` : « Commande expirée, aucun débit, places libérées », lien vers la séance ;
  - `REMBOURSEE` : « Séance annulée, commande remboursée ».

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/orders/{commande_id}` | `lireCommande` | oui |
| GET | `/api/v1/shows/{seance_id}` | `lireSeanceParId` | oui |
| GET | `/api/v1/events/{evenement_id}` | `lireEvenement` | oui |
| GET | `/api/v1/tickets?page=&size=` (filtrés par `commande_id`, voir Q3) | `listerBillets` | non |

- **Chargement** : en-tête en `Chargement` ; billets : « Émission de vos billets en cours ».
- **Vide** : `CONFIRMEE` sans billet après relectures : « Vos billets sont en cours
  d'émission, ils arriveront aussi par e-mail ».
- **Erreur** : 404 `ORDER_NOT_FOUND` (aussi pour la commande d'un autre client) en page
  introuvable ; 503 en `Erreur`.

```text
+--------------------------------------------------------------------+
| Commande du 12/11 à 18h04                      [ CONFIRMÉE ]       |
| Nom de l'événement - sam. 12/12 20h - Salle X, Lyon                |
|                                                                    |
| Paiement accepté. Vos billets arrivent aussi par e-mail.           |
|                                                                    |
| Rang B, place 2 (Or)   45 EUR   Billet émis   [Voir le billet]     |
| Rang B, place 3 (Or)   45 EUR   Émission en cours...               |
| Total                  90 EUR                                      |
|                                                                    |
| [Mes billets]   [Mes commandes]                                    |
+--------------------------------------------------------------------+
```

## E06 Mes commandes

- **Objectif** : retrouver ses commandes, reprendre un paiement en attente.
- **US** : US3, US5, US6. **Rôle** : `customer`.
- **Données** : par commande : date, événement et séance, nombre de places, total, statut ;
  action selon le statut (« Payer » si `EN_ATTENTE`, « Voir » sinon). Liste filtrée par
  l'appelant côté back, jamais par un paramètre du front.

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/orders?page=&size=` | `listerCommandes` | oui |
| GET | `/api/v1/shows/{seance_id}` (par séance distincte, en cache) | `lireSeanceParId` | oui |
| GET | `/api/v1/events/{evenement_id}` (par événement distinct, en cache) | `lireEvenement` | oui |

- **Chargement** : `TableauPagine` en `Chargement`.
- **Vide** : « Vous n'avez pas encore de commande », action « Voir les événements ».
- **Erreur** : 503 en `Erreur` ; séance ou événement illisible : ligne affichée avec
  « Séance indisponible » plutôt que toute la page en erreur.

```text
+--------------------------------------------------------------------+
| Mes commandes                                                      |
| +--------+----------------------------+--------+--------+--------+ |
| | Date   | Séance                     | Total  | Statut |        | |
| +--------+----------------------------+--------+--------+--------+ |
| | 12/11  | Nom, sam. 12/12 20h        | 90 EUR | Payée  | [Voir] | |
| | 12/11  | Nom, dim. 13/12 16h        | 25 EUR | Attente| [Payer]| |
| | 10/11  | Nom, ven. 04/12 21h        | 50 EUR | Expirée| [Voir] | |
| | 02/11  | Nom, sam. 28/11 20h        | 45 EUR | Rembour| [Voir] | |
| +--------+----------------------------+--------+--------+--------+ |
| < Précédent   Page 1 / 1   Suivant >                               |
+--------------------------------------------------------------------+
```

## E07 Mes billets

- **Objectif** : retrouver tous ses billets.
- **US** : US4 (billets émis), US6 (billets annulés). **Rôle** : `customer`.
- **Données** : par billet : événement, date, lieu, place, statut (`EMIS`, `ANNULE`), date
  d'émission ; lien vers E08.

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/tickets?page=&size=` | `listerBillets` | **non** |
| GET | `/api/v1/shows/{seance_id}` (par séance distincte) | `lireSeanceParId` | oui |
| GET | `/api/v1/events/{evenement_id}` (par événement distinct) | `lireEvenement` | oui |

- **Chargement** : liste en `Chargement`.
- **Vide** : « Aucun billet pour l'instant », action « Voir les événements ».
- **Erreur** : 503 en `Erreur`. Tant que `listerBillets` n'est pas codé (Q2), l'écran ne peut
  pas être livré.

```text
+--------------------------------------------------------------------+
| Mes billets                                                        |
| +-----------------------------+  +-----------------------------+   |
| | Nom de l'événement          |  | Nom de l'événement          |   |
| | sam. 12/12 20h, Salle X     |  | dim. 28/11 20h, Salle Y     |   |
| | Rang B, place 2             |  | Rang A, place 7             |   |
| | Valable                     |  | Annulé (séance annulée)     |   |
| | [Afficher le QR code]       |  | [Voir]                      |   |
| +-----------------------------+  +-----------------------------+   |
| < Précédent   Page 1 / 1   Suivant >                               |
+--------------------------------------------------------------------+
```

## E08 Billet et QR code

- **Objectif** : présenter son billet à l'entrée.
- **US** : US4, US6. **Rôle** : `customer`.
- **Données** : événement, date, lieu, place, statut ; QR code dessiné côté front à partir de
  `qr_code` (identifiant signé, aucune donnée lisible) ; pas de QR si `ANNULE`.

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/tickets/{billet_id}` | `lireBillet` | **non** |
| GET | `/api/v1/shows/{seance_id}` | `lireSeanceParId` | oui |
| GET | `/api/v1/events/{evenement_id}` | `lireEvenement` | oui |
| GET | `/api/v1/venues/{lieu_id}` | `lireLieu` | oui |

- **Chargement** : `Chargement`.
- **Vide** : sans objet.
- **Erreur** : 404 `TICKET_NOT_FOUND` (aussi pour le billet d'un autre client) en page
  introuvable ; 503 en `Erreur`.

```text
+--------------------------------------------------------------------+
| < Mes billets                                                      |
| Nom de l'événement                                                 |
| sam. 12/12 20h - Salle X, 1 rue ..., Lyon                          |
| Rang B, place 2 - catégorie Or                                     |
|                                                                    |
|                  +------------------+                              |
|                  |   ### QR ###     |   (alt : « QR code du billet |
|                  |   ### QR ###     |    rang B place 2 »)         |
|                  +------------------+                              |
|                  Billet valable - émis le 12/11                    |
|                                                                    |
| (si ANNULE : pas de QR, « Billet annulé : séance annulée et        |
|  commande remboursée »)                                            |
+--------------------------------------------------------------------+
```

## E10 Espace organisateur : événements

- **Objectif** : point d'entrée de l'organisateur, liste de ses événements.
- **US** : US6. **Rôle** : `admin` (jamais visible d'un client, CA1 de BIL-022).
- **Données** : événements (nom, date de création) paginés, recherche `q` ; actions « Créer un
  événement », « Lieux ».

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/events?q=&page=&size=` | `listerEvenements` | oui |

- **Chargement** : `TableauPagine` en `Chargement`.
- **Vide** : « Aucun événement », action « Créer un événement ».
- **Erreur** : 503 en `Erreur`.

```text
+--------------------------------------------------------------------+
| Espace organisateur                                                |
| [Créer un événement]  [Lieux]            [ Rechercher...    ]      |
| +-------------------------------+--------------+-----------+       |
| | Événement                     | Créé le      |           |       |
| +-------------------------------+--------------+-----------+       |
| | Nom de l'événement            | 01/11        | [Gérer]   |       |
| | Nom de l'événement            | 28/10        | [Gérer]   |       |
| +-------------------------------+--------------+-----------+       |
| < Précédent   Page 1 / 2   Suivant >                               |
+--------------------------------------------------------------------+
```

## E11 Nouvel événement

- **Objectif** : créer un événement.
- **US** : US6. **Rôle** : `admin`.
- **Données** : formulaire nom, description ; erreurs de validation champ par champ (CA2 de
  BIL-022, lues dans `erreurs` du Problem Details).

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| POST | `/api/v1/events` | `creerEvenement` | oui |

- **Chargement** : bouton « Créer » désactivé pendant l'envoi.
- **Vide** : sans objet (formulaire).
- **Erreur** : 422 `REQUETE_INVALIDE` sous chaque champ ; 403 `ROLE_MANQUANT` ou
  `SCOPE_MANQUANT` en `Erreur` ; 503 en `Erreur`. Succès : notification et renvoi vers E12.
- La modification d'un événement n'a pas de route : voir Q8.

```text
+--------------------------------------------------------------------+
| < Espace organisateur                                              |
| Nouvel événement                                                   |
| Nom *          [______________________________]                    |
|                (erreur du champ)                                   |
| Description    [______________________________]                    |
|                [______________________________]                    |
| [Créer]   [Annuler]                                                |
+--------------------------------------------------------------------+
```

## E12 Gérer un événement

- **Objectif** : voir les séances d'un événement et en programmer.
- **US** : US6. **Rôle** : `admin`.
- **Données** : nom, description ; séances (date, lieu, catégories, état annulée) ; actions
  « Programmer une séance », « Voir » par séance.

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/events/{evenement_id}` | `lireEvenement` | oui |
| GET | `/api/v1/events/{evenement_id}/shows?page=&size=` | `listerSeances` | oui |
| GET | `/api/v1/venues/{lieu_id}` (par lieu distinct) | `lireLieu` | oui |

- **Chargement** : en-tête puis tableau en `Chargement`.
- **Vide** : « Aucune séance », action « Programmer une séance ».
- **Erreur** : 404 `EVENT_NOT_FOUND` en page introuvable ; 503 en `Erreur`.

```text
+--------------------------------------------------------------------+
| < Espace organisateur                                              |
| Nom de l'événement                                [Modifier] (Q8)  |
| Description...                                                     |
|                                                                    |
| Séances                                  [Programmer une séance]   |
| +----------------+----------------+-------------------+---------+  |
| | Date           | Lieu           | Catégories        |         |  |
| +----------------+----------------+-------------------+---------+  |
| | sam. 12/12 20h | Salle X, Lyon  | Or 45, Argent 25  | [Voir]  |  |
| | dim. 13/12 16h | Salle X, Lyon  | Annulée           | [Voir]  |  |
| +----------------+----------------+-------------------+---------+  |
+--------------------------------------------------------------------+
```

## E13 Nouvelle séance

- **Objectif** : programmer une séance dans un lieu, avec ses catégories de places.
- **US** : US6. **Rôle** : `admin`.
- **Données** : lieu (liste déroulante), date et heure de début ; catégories répétables (nom,
  prix en euros converti en centimes, rangs avec leur nombre de places).

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/venues?page=&size=100` | `listerLieux` | oui |
| POST | `/api/v1/events/{evenement_id}/shows` | `creerSeance` | oui |

- **Chargement** : liste des lieux en `Chargement` ; « Programmer » désactivé pendant l'envoi.
- **Vide** : aucun lieu : « Créez d'abord un lieu », lien vers E15.
- **Erreur** : 422 `REQUETE_INVALIDE` champ par champ, 422 `SHOW_START_IN_PAST` sous la date ;
  404 `EVENT_NOT_FOUND` ou `VENUE_NOT_FOUND` ; 503. Succès : renvoi vers E12 (les places sont
  créées ensuite par Billets, en asynchrone).

```text
+--------------------------------------------------------------------+
| < Nom de l'événement                                               |
| Nouvelle séance                                                    |
| Lieu *     [ Salle X, Lyon        v]                               |
| Début *    [ jj/mm/aaaa ] [ hh:mm ]                                |
|                                                                    |
| Catégorie 1   Nom [ Or     ]  Prix [ 45,00 ] EUR   [Retirer]      |
|    Rangs : [ A ] places [ 20 ]  [ B ] places [ 20 ]  [+ rang]      |
| Catégorie 2   Nom [ Argent ]  Prix [ 25,00 ] EUR   [Retirer]      |
|    Rangs : [ C ] places [ 30 ]                       [+ rang]      |
| [+ Ajouter une catégorie]                                          |
|                                                                    |
| [Programmer]   [Annuler]                                           |
+--------------------------------------------------------------------+
```

## E14 Séance : remplissage et annulation

- **Objectif** : suivre le remplissage d'une séance et l'annuler.
- **US** : US6. **Rôle** : `admin`.
- **Données** : événement, date, lieu, catégories ; places indisponibles sur total, par
  catégorie (calcul front sur `listerPlaces`, approximation : verrouillées et vendues
  confondues, voir Q4) ; état annulée ; action « Annuler la séance » avec
  `DialogueConfirmation` explicite (« Tous les acheteurs seront remboursés »).

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/shows/{seance_id}` | `lireSeanceParId` | oui |
| GET | `/api/v1/events/{evenement_id}` | `lireEvenement` | oui |
| GET | `/api/v1/seats?seance_id=&page=&size=100` (toutes les pages) | `listerPlaces` | oui |
| POST | `/api/v1/events/{evenement_id}/shows/{seance_id}/cancellation` | `annulerSeance` | oui |
| (ventes réelles par séance) | aucune | aucune | à créer (Q4) |

- **Chargement** : chiffres en `Chargement` ; dialogue : « Confirmer » désactivé pendant
  l'envoi.
- **Vide** : aucune place encore créée : « Places en cours de création ».
- **Erreur** : 409 `SHOW_ALREADY_CANCELLED` ou `SHOW_ALREADY_STARTED` (message, séance
  relue) ; 404 `SHOW_NOT_FOUND` ; 503. Succès : notification « Séance annulée, remboursements
  en cours », bouton retiré.

```text
+--------------------------------------------------------------------+
| < Nom de l'événement                                               |
| Séance du sam. 12/12 20h - Salle X, Lyon                           |
|                                                                    |
| Remplissage                                                        |
| +-----------+--------------------+---------+                       |
| | Catégorie | Places prises      | Total   |                       |
| +-----------+--------------------+---------+                       |
| | Or        | 31                 | 40      |                       |
| | Argent    | 12                 | 30      |                       |
| +-----------+--------------------+---------+                       |
| (places prises = verrouillées ou vendues)                          |
|                                                                    |
| [Annuler la séance]                                                |
|                                                                    |
|   +-- Dialogue -------------------------------------------+        |
|   | Annuler la séance du 12/12 ?                          |        |
|   | Tous les acheteurs seront remboursés et prévenus.     |        |
|   | [Annuler]                       [Confirmer]           |        |
|   +-------------------------------------------------------+        |
+--------------------------------------------------------------------+
```

## E15 Lieux

- **Objectif** : lister les lieux et en créer un (préalable à une séance).
- **US** : US6. **Rôle** : `admin`.
- **Données** : lieux (nom, adresse, ville) paginés ; formulaire nom, adresse, ville.

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| GET | `/api/v1/venues?page=&size=` | `listerLieux` | oui |
| POST | `/api/v1/venues` | `creerLieu` | oui |

- **Chargement** : tableau en `Chargement` ; « Créer » désactivé pendant l'envoi.
- **Vide** : « Aucun lieu », formulaire visible.
- **Erreur** : 422 champ par champ ; 503 en `Erreur`. Succès : notification, liste relue.

```text
+--------------------------------------------------------------------+
| < Espace organisateur                                              |
| Lieux                                                              |
| +--------------------+--------------------------+----------+       |
| | Nom                | Adresse                  | Ville    |       |
| +--------------------+--------------------------+----------+       |
| | Salle X            | 1 rue ...                | Lyon     |       |
| +--------------------+--------------------------+----------+       |
| < Précédent   Page 1 / 1   Suivant >                               |
|                                                                    |
| Nouveau lieu                                                       |
| Nom * [__________]  Adresse * [________________]  Ville * [______] |
| [Créer le lieu]                                                    |
+--------------------------------------------------------------------+
```

## E16 Salle d'attente (V2)

- **Objectif** : attendre son tour à l'ouverture des ventes, puis être admis sur E03.
- **US** : US8 (BIL-015 pour le back, BIL-023 pour le front, phase V2). **Rôle** : `customer`.
- **Données** : position, estimation d'attente, relue au plus toutes les quelques secondes ;
  à l'admission, jeton d'admission transmis à la réservation ; rafraîchir la page ne fait pas
  perdre sa place (CA1 de BIL-023).

| Méthode | Chemin | operationId | Codé |
| --- | --- | --- | --- |
| (entrer dans la file, lire sa position) | service `file-attente` | à définir | **à créer** |

- Aucune route : le contrat du service `file-attente` sera écrit par BIL-015. Écran
  maintenu ici pour couvrir US8 ; ses routes seront fixées avec ce contrat.
- **Chargement** : « Connexion à la file d'attente… ».
- **Vide** : sans objet.
- **Erreur** : file indisponible en `Erreur` avec « Réessayer ».

```text
+--------------------------------------------------------------------+
| Nom de l'événement - sam. 12/12 20h                                |
|                                                                    |
| Vous êtes dans la file d'attente                                   |
| Position : 1 254           Attente estimée : environ 6 min         |
| [=========>.................................]   (role="status")    |
|                                                                    |
| Gardez cette page ouverte : vous serez redirigé vers le plan de    |
| salle à votre tour.                                                |
+--------------------------------------------------------------------+
```

---

## Routes d'API manquantes ou à adapter

| Besoin | Écran | Route | État |
| --- | --- | --- | --- |
| Réserver sans payer (compte à rebours avant paiement) | E03, E04 | `creerCommande` | Q1 |
| Lister ses billets | E05, E07 | `GET /api/v1/tickets` (`listerBillets`) | cible, non codé |
| Lire un billet et son QR code | E08 | `GET /api/v1/tickets/{billet_id}` (`lireBillet`) | idem |
| Billets d'une commande | E05 | filtre `commande_id` sur `listerBillets` | Q3 |
| Disponibilité et ventes par séance | E02, E14 | aucune | Q4 |
| Distinguer verrouillée et vendue | E03 | champ de `Place` | Q5 |
| Libellé de place dans commande et billet | E04 à E08 | `rang`, `numero` | Q6 |
| Abandonner une commande en attente | E04 | aucune | Q7 |
| Modifier un événement ou une séance | E11, E12 | aucune | Q8 |
| File d'attente | E16 | service `file-attente` | BIL-015 (V2) |

## Questions

**Q1. Réserver avant de payer.** `creerCommande` réserve et paie en un seul appel ; aucune
route client ne verrouille seule (`verrouillerPlace` est réservé au client `services`). Le
compte à rebours de BIL-020 (« verrouillage », « expiration renvoyée par l'API ») n'a donc rien
à afficher avant le paiement. **Recommandation** : rendre `carte_test` facultatif dans
`CommandeCreation` ; sans carte, `creerCommande` s'arrête après les verrous et répond 201
`EN_ATTENTE` avec `expire_le`, puis le client paie par `payerCommande` (déjà codée). Les
revendeurs gardent l'appel en une fois. Petit changement de contrat Commandes, à faire avant
BIL-020 (ticket back dédié ou étape de BIL-020). À défaut : variante décrite sous E03.

**Q2. `listerBillets` et `lireBillet` non codés.** Prévus dans `docs/contrats/billets.yaml`,
absents de `services/billets`. **Recommandation** : un ticket back Billets avant BIL-021
(BIL-021 en dépend), qui inclut Q3 et Q6.

**Q3. Billets d'une commande.** E05 doit montrer les billets d'une seule commande.
**Recommandation** : paramètre facultatif `commande_id` sur `listerBillets`, toujours combiné
au filtre sur l'appelant (route non codée, ajout sans coût).

**Q4. Disponibilité et ventes par séance.** Aucune route ne donne un nombre de places libres
(E02) ni les ventes d'une séance (E14, « tableau des ventes » de BIL-022) ; `listerPlaces` ne
filtre pas et ne distingue pas verrouillée et vendue. **Recommandation** : au MVP, E14 calcule
« places prises / total » en lisant toutes les pages de `listerPlaces`, et E02 n'affiche pas
la disponibilité (seulement « Annulée ») ; noter une route d'agrégat admin (Billets ou
Commandes) comme amélioration, hors BIL-022.

**Q5. États d'une place.** BIL-020 demande libre, verrouillée, vendue, sélectionnée ; l'API
n'expose que `disponible`. **Recommandation** : garder trois états à l'écran (libre,
indisponible, sélectionnée) : le client n'a pas à savoir qu'une place est seulement verrouillée,
et le contrat Billets reste inchangé.

**Q6. Libellé des places.** `LigneCommande` et `Billet` ne portent que `place_id` ; afficher
« Rang B, place 2 » oblige à relire toutes les places de la séance. **Recommandation** :
ajouter `rang` et `numero` à `Billet` (non codé, sans coût) ; pour `LigneCommande`, relire
`listerPlaces` côté front au MVP, sans toucher au contrat Commandes.

**Q7. Abandonner une commande.** Aucune route ne libère une commande `EN_ATTENTE` avant
`expire_le`. **Recommandation** : « Abandonner » ne fait que revenir à la séance ; les places
se libèrent à l'expiration (US5). Pas de nouvelle route au MVP.

**Q8. Modifier un événement ou une séance.** BIL-022 parle de « création et modification »,
le contrat Catalogue n'a que la création. **Recommandation** : BIL-022 se limite à la création
et à l'annulation ; la modification devient un ticket séparé (back Catalogue puis front) si le
développeur la veut. Le bouton « Modifier » de E12 n'apparaît pas tant que la route n'existe
pas.
