# Parcours du front billetterie

Parcours par profil (BIL-018). Les écrans `E01` à `E16` sont décrits dans `ecrans.md`, leurs
routes React dans `routes.md`. Les décisions encore ouvertes (Q1 à Q8) sont listées à la fin de
`ecrans.md` ; les parcours ci-dessous suivent leur recommandation.

## Profils

| Profil | Rôle Keycloak | Connexion | User stories |
| --- | --- | --- | --- |
| Visiteur | aucun | non connecté | US1 |
| Client | `customer` | Authorization Code + PKCE (`frontend`) | US2, US3, US4, US5, US6, US8 |
| Organisateur | `admin` | Authorization Code + PKCE (`frontend`) | US6 |
| Revendeur | `partner` | Client Credentials (`revendeur-test`) | US7 |

**US7 (revendeur) n'a aucun écran** : le revendeur est une application qui appelle l'API avec
son propre client Keycloak (Client Credentials), sans utilisateur humain ni navigateur. Sa
documentation est `docs/contrats/partenaires.yaml`. Le front ne propose donc aucune route au rôle
`partner` ; un compte `partner` connecté par erreur au front voit les pages publiques et
« Accès refusé » ailleurs.

Les rôles sont sans hiérarchie : le compte `admin.test` ne porte que `admin` et ne peut pas
acheter (`orders:write` est réservé à `customer` et `partner`).

## Visiteur (US1)

Le visiteur parcourt le catalogue sans compte. Il voit le plan de salle d'une séance ; choisir
des places le fait passer par la connexion, puis il revient sur la même séance avec sa sélection
(gardée dans l'URL).

```mermaid
flowchart TD
    A["E01 Catalogue des événements"] -->|filtre q, ville, du, au| A
    A -->|clic sur un événement| B["E02 Fiche événement"]
    B -->|clic sur une séance| C["E03 Séance et plan de salle"]
    C -->|sélectionne des places| C
    C -->|Réserver, non connecté| K["Keycloak : connexion ou inscription"]
    K -->|/connexion/rappel| C2["E03 même séance, sélection conservée"]
    C2 --> S["suite : parcours client"]
    B -->|séance annulée| X["Mention Annulée, pas de lien d'achat"]
```

## Client (US2 à US6, US8)

Parcours d'achat, en deux temps comme dans la conception : réservation (verrou de 10 minutes
avec compte à rebours), puis paiement. Il suppose la recommandation de Q1 (réserver sans payer) ;
la variante sans changement du back est décrite dans `ecrans.md` (E03 et E04).

```mermaid
flowchart TD
    C["E03 Séance et plan de salle"] -->|Réserver : creerCommande sans carte| R{Réponse}
    R -->|409 SEAT_ALREADY_TAKEN| C1["E03 plan rafraîchi, message place prise"]
    R -->|409 TICKET_LIMIT_EXCEEDED| C2["E03 message plafond de 10 billets"]
    R -->|201 EN_ATTENTE| P["E04 Paiement, compte à rebours expire_le"]
    W["E16 Salle d'attente (V2, US8)"] -->|admis| C
    P -->|Payer : payerCommande| Q{Réponse}
    Q -->|200 CONFIRMEE| D["E05 Suivi de commande : confirmée"]
    Q -->|402 PAYMENT_REFUSED| E["E05 commande expirée, places libérées"]
    Q -->|503 SERVICE_INDISPONIBLE| P2["E04 réessayer avant expire_le"]
    P2 --> P
    P -->|compte à rebours à zéro| E
    E -->|Choisir d'autres places| C
    D -->|billets émis, e-mail envoyé| F["E07 Mes billets"]
    F --> G["E08 Billet et QR code"]
```

Suivi après achat, depuis la navigation (« Mes commandes », « Mes billets ») :

```mermaid
flowchart TD
    N["Navigation client"] --> L["E06 Mes commandes"]
    N --> F["E07 Mes billets"]
    L -->|EN_ATTENTE| P["E04 Paiement (reprise avant expire_le)"]
    L -->|CONFIRMEE| D["E05 Suivi : billets de la commande"]
    L -->|EXPIREE| E["E05 Suivi : expirée, aucun débit (US5)"]
    L -->|REMBOURSEE| RB["E05 Suivi : séance annulée, remboursée (US6)"]
    F -->|EMIS| G["E08 Billet et QR code"]
    F -->|ANNULE| GA["E08 Billet annulé, sans QR code (US6)"]
```

US5 vue du client : une place abandonnée par un autre redevient libre sur E03 (le plan est
relu), et sa propre commande non payée passe en `EXPIREE` sur E05 et E06.

US6 vue du client : la séance porte « Annulée » sur E02 et E03, la commande passe en
`REMBOURSEE` (E05, E06), le billet en `ANNULE` (E07, E08) ; l'e-mail part côté back.

## Organisateur (US6)

L'organisateur (`admin`) prépare son catalogue, suit le remplissage d'une séance et l'annule.

```mermaid
flowchart TD
    O["E10 Espace organisateur : événements"] -->|Créer un événement| N["E11 Nouvel événement"]
    N -->|201| G["E12 Gérer un événement"]
    O -->|clic sur un événement| G
    O -->|Lieux| L["E15 Lieux"]
    L -->|creerLieu| L
    G -->|Programmer une séance| S["E13 Nouvelle séance"]
    S -->|201| G
    S -->|aucun lieu| L
    G -->|clic sur une séance| V["E14 Séance : remplissage et annulation"]
    V -->|Annuler la séance| DC["Dialogue de confirmation"]
    DC -->|Confirmer : annulerSeance| R{Réponse}
    R -->|200| V2["E14 séance annulée, remboursements en cours"]
    R -->|409 SHOW_ALREADY_STARTED ou SHOW_ALREADY_CANCELLED| V3["E14 message, rien ne change"]
    DC -->|Annuler| V
```

## Couverture des user stories

| US | Parcours | Écrans |
| --- | --- | --- |
| US1 | Visiteur | E01, E02, E03 |
| US2 | Client | E03, E04 |
| US3 | Client | E04, E05 |
| US4 | Client | E05, E07, E08 |
| US5 | Client | E03, E04, E05, E06 |
| US6 | Organisateur (annuler), client (subir) | E10 à E15 ; E05 à E08 côté client |
| US7 | Aucun (API seule) | aucun |
| US8 | Client (V2) | E16 |
