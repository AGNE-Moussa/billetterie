# Routes React du front billetterie

Plan des routes de l'application (BIL-018), dans la table de `frontend/src/RoutesApplication.tsx`
et sous `MiseEnPage`. Écrans : `ecrans.md` ; parcours : `parcours.md`.

## Gardes

- **Public** : aucune garde.
- **`customer`** : `GardeRoles roles={["customer"]}`. **`admin`** : `GardeRoles
  roles={["admin"]}`. Rôles sans hiérarchie : `admin` n'ouvre pas les routes `customer`.
- Comportement de `GardeRoles` (BIL-F27) : session en chargement, message « Chargement de la
  session » ; non connecté, redirection vers Keycloak avec l'URL courante (chemin, `search`,
  `hash`) comme retour, puis `/connexion/rappel` y ramène (`cheminInterne`) ; connecté sans le
  rôle, `PageAccesRefuse`.
- Les routes `/organisateur/...` partagent une seule garde `admin` (route parente sans chemin
  propre qui rend `GardeRoles` autour de ses routes enfants). Même principe pour les routes
  `customer`.
- Aucun écran pour `partner` (US7 : API seule).
- La garde du front n'est qu'un confort : chaque service revérifie le jeton et ses scopes.

## Table des routes

| Chemin | Écran | Rôles | Garde | Ticket |
| --- | --- | --- | --- | --- |
| `/` | E01 Catalogue (`?q=&ville=&du=&au=&page=`) | tous | aucune | BIL-019 |
| `/evenements/:evenementId` | E02 Fiche événement | tous | aucune | BIL-019 |
| `/seances/:seanceId` | E03 Plan de salle (`?places=id1,id2`) | tous | aucune | BIL-020 |
| `/seances/:seanceId/attente` | E16 Salle d'attente (V2) | `customer` | `GardeRoles` | BIL-023 |
| `/commandes` | E06 Mes commandes (`?page=`) | `customer` | `GardeRoles` | BIL-021 |
| `/commandes/:commandeId` | E05 Suivi d'une commande | `customer` | `GardeRoles` | BIL-021 |
| `/commandes/:commandeId/paiement` | E04 Paiement | `customer` | `GardeRoles` | BIL-020 |
| `/billets` | E07 Mes billets (`?page=`) | `customer` | `GardeRoles` | BIL-021 |
| `/billets/:billetId` | E08 Billet et QR code | `customer` | `GardeRoles` | BIL-021 |
| `/organisateur` | E10 Événements | `admin` | `GardeRoles` | BIL-022 |
| `/organisateur/evenements/nouveau` | E11 Nouvel événement | `admin` | `GardeRoles` | BIL-022 |
| `/organisateur/evenements/:evenementId` | E12 Gérer | `admin` | `GardeRoles` | BIL-022 |
| `/organisateur/evenements/:evenementId/seances/nouvelle` | E13 | `admin` | idem | BIL-022 |
| `/organisateur/seances/:seanceId` | E14 Remplissage | `admin` | `GardeRoles` | BIL-022 |
| `/organisateur/lieux` | E15 Lieux | `admin` | `GardeRoles` | BIL-022 |
| `/connexion/rappel` | Retour de Keycloak (`CHEMIN_RAPPEL`, existant) | tous | aucune | BIL-F27 |
| `*` | Page introuvable (existant) | tous | aucune | BIL-F28 |

E04 sert aussi à BIL-021 (paiement) ; E13 est « Nouvelle séance ».

Notes :

- E03 est public pour consulter ; seul le bouton « Réserver » demande la connexion
  (`seConnecter` avec l'URL courante, `?places=` compris), puis appelle `creerCommande`. Un
  `partner` ou un `admin` connecté voit « Réservé aux clients » à la place du bouton.
- Après la réservation (Q1 de `ecrans.md`), E03 navigue vers
  `/commandes/:commandeId/paiement` : l'identifiant de commande dans l'URL rend la page
  rechargeable sans perdre le compte à rebours. Après le paiement, E04 navigue vers
  `/commandes/:commandeId` (confirmation).
- E04 sur une commande qui n'est plus `EN_ATTENTE` redirige vers `/commandes/:commandeId`.
- Les filtres et la page vivent dans l'URL (`useSearchParams`) : lien partageable, bouton
  retour du navigateur cohérent.
- Ressource d'un autre client (`ORDER_NOT_FOUND`, `TICKET_NOT_FOUND`) : même rendu que
  `PageIntrouvable`, jamais « Accès refusé ».

## Navigation principale

Liens de `LIENS_NAVIGATION` (`frontend/src/navigation.ts`), filtrés par `Navigation` avec la
même règle que `GardeRoles` :

| Libellé | Chemin | `roles` |
| --- | --- | --- |
| Événements | `/` | absent (public) |
| Mes commandes | `/commandes` | `["customer"]` |
| Mes billets | `/billets` | `["customer"]` |
| Espace organisateur | `/organisateur` | `["admin"]` |

Chaque ticket front ajoute ses liens en même temps que ses routes : BIL-019 renomme
« Accueil » en « Événements », BIL-021 ajoute « Mes commandes » et « Mes billets », BIL-022
ajoute « Espace organisateur ».

## Décisions proposées

**R1. Catalogue sur `/`.** Le catalogue (E01) remplace le contenu de `PageAccueil` plutôt que
d'ajouter une route `/evenements` : une seule entrée, la vitrine demandée par BIL-019.
**Recommandation** : retenir `/` ; `/evenements/:evenementId` reste le détail.

**R2. Chemins en français.** Comme `/connexion/rappel` existant, les chemins du front sont en
français (`/seances`, `/commandes`, `/billets`, `/organisateur`), distincts des chemins d'API
en anglais (`/api/v1/shows`, ...). **Recommandation** : retenir.

**R3. Séance sans l'événement dans le chemin.** `/seances/:seanceId` plutôt que
`/evenements/:evenementId/seances/:seanceId`, grâce à `lireSeanceParId` : URL plus courte et
seul identifiant connu depuis une commande ou un billet. **Recommandation** : retenir ; même
choix pour `/organisateur/seances/:seanceId`.
