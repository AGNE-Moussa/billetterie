"""Commandes : entités, erreurs métier, port du dépôt et cas d'usage, sans SQLAlchemy ni httpx.

Parcours de `creer_commande` (décisions Q1 à Q3, Q13 à Q19 de BIL-008) : clé d'idempotence,
séance lue dans Catalogue, plafond et création EN_ATTENTE sous verrou consultatif, verrous de
réservation, reverrouillage en confirmation, Paiements, puis CONFIRMEE et
ticketing.order.confirmed dans la même transaction. Chaque échec synchrone sur une place ou un
paiement passe la commande EXPIREE et publie ticketing.order.expired. Le numéro de carte ne fait
que transiter vers Paiements : jamais enregistré ni journalisé.
"""

import logging
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from commandes.domaine.services import (
    ClientBillets,
    ClientCatalogue,
    ClientPaiements,
    SeanceLue,
)
from commun.auth import Appelant
from commun.erreurs import ErreurMetier
from commun.evenements import Evenement

journal = logging.getLogger(__name__)

# Publiés par l'outbox (décisions Q2 et Q8 de BIL-008).
EVENEMENT_COMMANDE_CONFIRMEE = "ticketing.order.confirmed"
EVENEMENT_COMMANDE_EXPIREE = "ticketing.order.expired"
# Statut d'un paiement accepté, lu dans Paiements (lirePaiement).
PAIEMENT_ACCEPTE = "ACCEPTE"
# Rôle Keycloak des revendeurs (realm billetterie) : leurs commandes sont au canal PARTENAIRE.
ROLE_PARTENAIRE = "partner"


class StatutCommande(StrEnum):
    EN_ATTENTE = "EN_ATTENTE"
    CONFIRMEE = "CONFIRMEE"
    EXPIREE = "EXPIREE"
    REMBOURSEE = "REMBOURSEE"


# Description du schéma StatutCommande du contrat (Pydantic la lit dans __doc__, sur une ligne).
StatutCommande.__doc__ = (
    "Transitions autorisées : EN_ATTENTE vers CONFIRMEE ou EXPIREE ; CONFIRMEE vers"
    " REMBOURSEE ; EXPIREE et REMBOURSEE sont finales. EXPIREE : non payée avant expire_le,"
    " paiement refusé, échec de verrou ou place perdue avant paiement, ou séance annulée alors"
    " que la commande était EN_ATTENTE (ticketing.show.cancelled). REMBOURSEE : remboursement"
    " après ticketing.show.cancelled ou ticketing.ticket.rejected (place refusée à l'émission"
    " du billet), reçu par ticketing.payment.refunded."
)


class CanalCommande(StrEnum):
    """Canal de vente d'une commande, déduit du rôle du jeton ; en base seulement, jamais exposé
    dans l'API ni dans les événements (BIL-012, décision Q3, H7)."""

    DIRECT = "DIRECT"
    PARTENAIRE = "PARTENAIRE"


def canal_de(appelant: Appelant) -> CanalCommande:
    """Canal de la commande créée par `appelant` (BIL-012, décision Q3 et question 4 du plan).

    PARTENAIRE dès que le jeton porte le rôle `partner`, même avec `customer` : la gateway traite
    ce jeton comme celui d'un revendeur ; DIRECT sinon.
    """
    if ROLE_PARTENAIRE in appelant.roles:
        return CanalCommande.PARTENAIRE
    return CanalCommande.DIRECT


@dataclass(frozen=True)
class LigneCommande:
    place_id: UUID
    # Prix de la catégorie de la place, en centimes ; None tant que son verrou n'a pas répondu
    # (décision Q13).
    montant: int | None


@dataclass(frozen=True)
class Commande:
    id: UUID
    # sub Keycloak de l'appelant (règle métier 6 : toute lecture filtre par ce champ).
    client: str
    # Claim email du jeton, None pour un revendeur (décision Q22).
    email: str | None
    cle_idempotence: str | None
    seance_id: UUID
    statut: StatutCommande
    lignes: tuple[LigneCommande, ...]
    montant_total: int
    cree_le: datetime
    # Fin du plus court des verrous de ses places ; None tant qu'aucun verrou n'a répondu.
    expire_le: datetime | None
    # Vrai dès que la commande a été envoyée au moins une fois à Paiements : avant de l'expirer,
    # Commandes lit alors son paiement (review BIL-008, point 3).
    paiement_demande: bool = False
    # Canal de vente (BIL-012, décision Q3) : fixé à la création par canal_de, en base
    # seulement. La valeur par défaut ne sert qu'aux commandes construites hors création.
    canal: CanalCommande = CanalCommande.DIRECT


@dataclass(frozen=True)
class PageResultat[T]:
    elements: list[T]
    total: int


class CommandeIntrouvable(ErreurMetier):
    """Commande inconnue ou d'un autre appelant : 404, jamais 403."""

    def __init__(self, commande_id: UUID) -> None:
        super().__init__(
            "ORDER_NOT_FOUND",
            404,
            f"Aucune commande avec l'identifiant {commande_id}.",
            titre="Commande introuvable",
        )


class CommandeNonEnAttente(ErreurMetier):
    def __init__(self, commande_id: UUID) -> None:
        super().__init__(
            "ORDER_NOT_PENDING",
            409,
            f"La commande {commande_id} n'est pas en attente de paiement.",
            titre="Commande non en attente",
        )


class SeanceIntrouvable(ErreurMetier):
    def __init__(self, seance_id: UUID) -> None:
        super().__init__(
            "SHOW_NOT_FOUND",
            404,
            f"Aucune séance avec l'identifiant {seance_id}.",
            titre="Séance introuvable",
        )


class SeanceAnnulee(ErreurMetier):
    def __init__(self, seance_id: UUID) -> None:
        super().__init__(
            "SHOW_CANCELLED", 409, f"La séance {seance_id} est annulée.", titre="Séance annulée"
        )


class SeanceCommencee(ErreurMetier):
    def __init__(self, seance_id: UUID) -> None:
        super().__init__(
            "SHOW_ALREADY_STARTED",
            409,
            f"La séance {seance_id} a déjà commencé.",
            titre="Séance commencée",
        )


class PlaceIntrouvable(ErreurMetier):
    def __init__(self, place_id: UUID) -> None:
        super().__init__(
            "SEAT_NOT_FOUND",
            404,
            f"Aucune place avec l'identifiant {place_id} dans cette séance.",
            titre="Place introuvable",
        )
        self.place_id = place_id


class PlaceDejaPrise(ErreurMetier):
    def __init__(self, place_id: UUID) -> None:
        super().__init__(
            "SEAT_ALREADY_TAKEN",
            409,
            f"La place {place_id} est déjà prise.",
            titre="Place déjà prise",
        )
        self.place_id = place_id


class LimiteBilletsDepassee(ErreurMetier):
    def __init__(self, limite: int) -> None:
        super().__init__(
            "TICKET_LIMIT_EXCEEDED",
            409,
            f"Au plus {limite} billets par client et par séance.",
            titre="Limite de billets dépassée",
        )


class RequeteEnCours(ErreurMetier):
    def __init__(self) -> None:
        super().__init__(
            "REQUEST_IN_PROGRESS",
            409,
            "Une requête de même Idempotency-Key est encore en cours.",
            titre="Requête en cours",
        )


class ReservationEnCours(ErreurMetier):
    """`payerCommande` pendant les verrous de réservation de `creerCommande` (`expire_le` encore
    inconnu) : 409 REQUEST_IN_PROGRESS, sans appel à Paiements (review BIL-008, point 2)."""

    def __init__(self, commande_id: UUID) -> None:
        super().__init__(
            "REQUEST_IN_PROGRESS",
            409,
            f"La réservation des places de la commande {commande_id} est encore en cours.",
            titre="Requête en cours",
        )


class PaiementRefuse(ErreurMetier):
    def __init__(self) -> None:
        super().__init__("PAYMENT_REFUSED", 402, "Le paiement est refusé.", titre="Paiement refusé")


class PaiementDejaExistant(ErreurMetier):
    """Réponse 409 PAYMENT_ALREADY_EXISTS de Paiements (ne devrait pas arriver, décision Q17)."""

    def __init__(self, commande_id: UUID) -> None:
        super().__init__(
            "PAYMENT_ALREADY_EXISTS",
            409,
            f"Un paiement différent existe déjà pour la commande {commande_id}.",
            titre="Paiement déjà existant",
        )


class PaiementIncoherent(ErreurMetier):
    """Paiements signale un paiement différent pour la commande (409 PAYMENT_ALREADY_EXISTS) :
    le montant est figé, cela ne devrait pas arriver ; 503, commande EN_ATTENTE (décision Q17)."""

    def __init__(self) -> None:
        super().__init__(
            "SERVICE_INDISPONIBLE",
            503,
            "Le service paiements est momentanément indisponible.",
            titre="Service indisponible",
        )


class DepotCommandes(Protocol):
    """Accès aux commandes ; lève `BaseIndisponible` (503) si la base ne répond pas.

    Toute lecture filtre par `client` (règle métier 6).
    """

    def transaction(self) -> AbstractAsyncContextManager[None]:
        """Transaction : les écritures et les événements du bloc réussissent ensemble."""
        ...

    async def reserver_cle(self, client: str, cle: str) -> bool:
        """Verrou consultatif de session sur (`client`, `cle`), tenu jusqu'à `liberer_cle` ;
        faux s'il est déjà pris (décision Q16)."""
        ...

    async def liberer_cle(self, client: str, cle: str) -> None:
        """Rend le verrou consultatif pris par `reserver_cle`."""
        ...

    async def verrouiller_plafond(self, client: str, seance_id: UUID) -> None:
        """`pg_advisory_xact_lock` sur (`client`, `seance_id`), dans la transaction en cours
        (décision Q3)."""
        ...

    async def compter_billets(self, client: str, seance_id: UUID) -> int:
        """Lignes des commandes EN_ATTENTE et CONFIRMEE du client sur la séance."""
        ...

    async def lire_commande(self, client: str, commande_id: UUID) -> Commande | None:
        """La commande du client, ou None (inconnue ou d'un autre client)."""
        ...

    async def lire_par_cle(self, client: str, cle: str) -> Commande | None:
        """La commande du client créée avec cette `Idempotency-Key`, ou None."""
        ...

    async def lister_commandes(self, client: str, page: int, size: int) -> PageResultat[Commande]:
        """Commandes du client, par création décroissante puis identifiant."""
        ...

    async def lister_a_expirer(self, maintenant: datetime, limite: int) -> list[Commande]:
        """Au plus `limite` commandes `EN_ATTENTE` de tous les clients dont `expire_le` (non
        NULL) est `<= maintenant`, par `expire_le` croissant (BIL-010, décisions Q4 et Q5).
        Lecture sans verrou : la tâche relit chaque commande sous `FOR UPDATE`."""
        ...

    async def ajouter_commande(self, commande: Commande) -> None:
        """Enregistre la commande et ses lignes."""
        ...

    async def fixer_montants(
        self,
        commande_id: UUID,
        montants: dict[UUID, int],
        montant_total: int,
        expire_le: datetime,
    ) -> None:
        """Montant de chaque ligne (par place), total et fin des verrous (décision Q13)."""
        ...

    async def changer_statut(
        self, commande_id: UUID, statut: StatutCommande, expire_le: datetime | None = None
    ) -> None:
        """Nouveau statut ; `expire_le` remplacé s'il est donné.

        `EN_ATTENTE` n'est demandé qu'au reverrouillage terminé, juste avant l'appel à
        Paiements : la commande est alors marquée `paiement_demande` (review, point 3).
        """
        ...

    async def publier(self, evenement: Evenement) -> None:
        """Range l'événement dans l'outbox, dans la transaction en cours."""
        ...


async def creer_commande(
    depot: DepotCommandes,
    catalogue: ClientCatalogue,
    billets: ClientBillets,
    paiements: ClientPaiements,
    maintenant: datetime,
    *,
    appelant: Appelant,
    seance_id: UUID,
    place_ids: Sequence[UUID],
    carte_test: str,
    cle_idempotence: str | None,
    limite_billets: int,
) -> tuple[Commande, bool]:
    """Crée, verrouille et paie une commande ; renvoie la commande et vrai si elle vient d'être
    créée (201), faux pour le rejeu d'une `Idempotency-Key` (200)."""
    client = appelant.identifiant
    if cle_idempotence is None:
        commande = await _creer(
            depot,
            catalogue,
            billets,
            paiements,
            maintenant,
            appelant=appelant,
            seance_id=seance_id,
            place_ids=place_ids,
            carte_test=carte_test,
            cle_idempotence=None,
            limite_billets=limite_billets,
        )
        return commande, True
    # Clé réservée avant tout appel sortant, tenue pendant toute la requête (décision Q16).
    if not await depot.reserver_cle(client, cle_idempotence):
        raise RequeteEnCours()
    try:
        existante = await depot.lire_par_cle(client, cle_idempotence)
        if existante is not None:
            # Rejeu d'une requête terminée : la commande dans son état courant, corps ignoré.
            return existante, False
        commande = await _creer(
            depot,
            catalogue,
            billets,
            paiements,
            maintenant,
            appelant=appelant,
            seance_id=seance_id,
            place_ids=place_ids,
            carte_test=carte_test,
            cle_idempotence=cle_idempotence,
            limite_billets=limite_billets,
        )
        return commande, True
    finally:
        await depot.liberer_cle(client, cle_idempotence)


async def payer_commande(
    depot: DepotCommandes,
    catalogue: ClientCatalogue,
    billets: ClientBillets,
    paiements: ClientPaiements,
    maintenant: datetime,
    *,
    appelant: Appelant,
    commande_id: UUID,
    carte_test: str,
) -> Commande:
    """Nouvel essai de paiement d'une commande EN_ATTENTE de l'appelant."""
    commande = await lire_commande(depot, appelant, commande_id)
    if commande.statut is not StatutCommande.EN_ATTENTE:
        raise CommandeNonEnAttente(commande_id)
    if commande.expire_le is None:
        # Verrous de réservation de creerCommande encore en cours (review, point 2).
        raise ReservationEnCours(commande_id)
    seance = await catalogue.lire_seance(commande.seance_id)
    try:
        _verifier_seance(seance, commande.seance_id, maintenant)
    except (SeanceAnnulee, SeanceCommencee):
        # Séance annulée ou commencée d'après Catalogue : la commande expire (décisions
        # d'implémentation) ; séance inconnue : 404, commande inchangée.
        await _expirer(depot, commande, paiements)
        raise
    return await _confirmer_et_payer(depot, billets, paiements, commande, carte_test)


async def expirer_commande_echue(
    depot: DepotCommandes, commande: Commande, paiements: ClientPaiements, maintenant: datetime
) -> bool:
    """Expiration par la tâche périodique (BIL-010) : même logique que les échecs de BIL-008
    (lecture de Paiements si `paiement_demande`, jamais de `POST`), seulement si la commande,
    relue sous `FOR UPDATE`, est encore EN_ATTENTE avec `expire_le <= maintenant` (H3).

    Renvoie vrai si cet appel l'a expirée ; lève `ServiceIndisponible` si Paiements ne répond
    pas (commande laissée EN_ATTENTE)."""
    return await _expirer(depot, commande, paiements, echue_a=maintenant)


async def lire_commande(depot: DepotCommandes, appelant: Appelant, commande_id: UUID) -> Commande:
    """La commande de l'appelant ; lève `CommandeIntrouvable` sinon."""
    commande = await depot.lire_commande(appelant.identifiant, commande_id)
    if commande is None:
        raise CommandeIntrouvable(commande_id)
    return commande


async def lister_commandes(
    depot: DepotCommandes, appelant: Appelant, page: int, size: int
) -> PageResultat[Commande]:
    """Page des commandes de l'appelant."""
    return await depot.lister_commandes(appelant.identifiant, page, size)


# --- Étapes ---------------------------------------------------------------------------------


def _verifier_seance(seance: SeanceLue | None, seance_id: UUID, maintenant: datetime) -> SeanceLue:
    if seance is None:
        raise SeanceIntrouvable(seance_id)
    if seance.annulee:
        raise SeanceAnnulee(seance_id)
    if seance.debut <= maintenant:
        raise SeanceCommencee(seance_id)
    return seance


async def _creer(
    depot: DepotCommandes,
    catalogue: ClientCatalogue,
    billets: ClientBillets,
    paiements: ClientPaiements,
    maintenant: datetime,
    *,
    appelant: Appelant,
    seance_id: UUID,
    place_ids: Sequence[UUID],
    carte_test: str,
    cle_idempotence: str | None,
    limite_billets: int,
) -> Commande:
    seance = _verifier_seance(await catalogue.lire_seance(seance_id), seance_id, maintenant)
    commande = Commande(
        id=uuid4(),
        client=appelant.identifiant,
        email=appelant.email,
        cle_idempotence=cle_idempotence,
        seance_id=seance_id,
        statut=StatutCommande.EN_ATTENTE,
        lignes=tuple(LigneCommande(place_id=place_id, montant=None) for place_id in place_ids),
        montant_total=0,
        cree_le=maintenant,
        expire_le=None,
        canal=canal_de(appelant),
    )
    # Plafond compté et commande créée sous le même verrou consultatif (client, séance) : deux
    # commandes simultanées du même client se comptent l'une l'autre (décisions Q3 et Q15).
    async with depot.transaction():
        await depot.verrouiller_plafond(commande.client, seance_id)
        deja = await depot.compter_billets(commande.client, seance_id)
        if deja + len(place_ids) > limite_billets:
            raise LimiteBilletsDepassee(limite_billets)
        await depot.ajouter_commande(commande)

    # Verrous de réservation au nom de la commande (décision Q1) ; tout échec expire la
    # commande et publie ticketing.order.expired (décisions Q2, Q18, Q19).
    montants: dict[UUID, int] = {}
    expirations: list[datetime] = []
    try:
        for place_id in place_ids:
            verrou = await billets.verrouiller_place(
                place_id, seance_id=seance_id, commande_id=commande.id, confirmation=False
            )
            # Prix de la catégorie de la place dans la séance lue (décision Q13).
            montants[place_id] = seance.prix_par_categorie[verrou.categorie_id]
            expirations.append(verrou.expire_le)
    except Exception:
        await _expirer(depot, commande)
        raise

    lignes = tuple(LigneCommande(place_id=p, montant=montants[p]) for p in place_ids)
    montant_total = sum(montants.values())
    expire_le = min(expirations)
    async with depot.transaction():
        # Transition gardée (review, point 1) : montants fixés seulement si la commande est
        # encore EN_ATTENTE, relue sous verrou de ligne.
        actuelle = await _lire_verrouillee(depot, commande)
        if actuelle.statut is StatutCommande.EN_ATTENTE:
            await depot.fixer_montants(commande.id, montants, montant_total, expire_le)
    if actuelle.statut is not StatutCommande.EN_ATTENTE:
        return _deja_traitee(actuelle)
    commande = replace(commande, lignes=lignes, montant_total=montant_total, expire_le=expire_le)
    return await _confirmer_et_payer(depot, billets, paiements, commande, carte_test)


async def _confirmer_et_payer(
    depot: DepotCommandes,
    billets: ClientBillets,
    paiements: ClientPaiements,
    commande: Commande,
    carte_test: str,
) -> Commande:
    # Reverrouillage en durée de confirmation juste avant Paiements : une place perdue expire
    # la commande sans débit ; Billets indisponible la laisse EN_ATTENTE (décision Q18).
    expirations: list[datetime] = []
    try:
        for ligne in commande.lignes:
            verrou = await billets.verrouiller_place(
                ligne.place_id,
                seance_id=commande.seance_id,
                commande_id=commande.id,
                confirmation=True,
            )
            expirations.append(verrou.expire_le)
    except (PlaceDejaPrise, PlaceIntrouvable):
        # Un essai précédent a pu être débité sans réponse : paiement lu avant d'expirer.
        await _expirer(depot, commande, paiements)
        raise
    expire_le = min(expirations)
    async with depot.transaction():
        # Transition gardée (review, point 1) : la commande, relue sous verrou de ligne, doit
        # être encore EN_ATTENTE ; sinon aucun appel à Paiements.
        actuelle = await _lire_verrouillee(depot, commande)
        if actuelle.statut is StatutCommande.EN_ATTENTE:
            await depot.changer_statut(commande.id, StatutCommande.EN_ATTENTE, expire_le)
        elif actuelle.statut is StatutCommande.EXPIREE:
            # Expirée (tâche de BIL-010) entre la lecture sans verrou et cette relecture : le
            # reverrouillage vient de prolonger ses verrous à la durée de confirmation. Nouvel
            # ticketing.order.expired (review BIL-010, point 1) : Billets les libère (comparer
            # puis supprimer), sans attendre leur expiration.
            journal.info(
                "Verrous reposés pour la commande %s déjà expirée : expiration republiée",
                commande.id,
            )
            await depot.publier(
                Evenement.creer(EVENEMENT_COMMANDE_EXPIREE, _donnees_expiration(commande))
            )
    if actuelle.statut is not StatutCommande.EN_ATTENTE:
        return _deja_traitee(actuelle)
    commande = replace(commande, expire_le=expire_le)

    try:
        await paiements.payer(
            commande_id=commande.id,
            seance_id=commande.seance_id,
            montant=commande.montant_total,
            carte_test=carte_test,
        )
    except (PaiementRefuse, SeanceAnnulee):
        # Réponse de Paiements connue : refus enregistré, ou séance annulée sans paiement
        # enregistré (décision Q20) ; aucun remboursement dû, rien à relire.
        await _expirer(depot, commande)
        raise
    except PaiementDejaExistant as erreur:
        journal.error("Paiements signale un paiement différent pour la commande %s", commande.id)
        raise PaiementIncoherent() from erreur

    # Confirmation et ticketing.order.confirmed dans la même transaction (outbox).
    async with depot.transaction():
        actuelle = await _lire_verrouillee(depot, commande)
        if actuelle.statut is StatutCommande.CONFIRMEE:
            # Une requête simultanée l'a déjà confirmée (même paiement, idempotent).
            return actuelle
        if actuelle.statut is not StatutCommande.EN_ATTENTE:
            # Expirée pendant l'appel à Paiements : débit sans billet (review, point 3).
            journal.error("Paiement accepté pour la commande %s déjà expirée", commande.id)
            raise CommandeNonEnAttente(commande.id)
        await depot.changer_statut(commande.id, StatutCommande.CONFIRMEE, commande.expire_le)
        await depot.publier(
            Evenement.creer(
                EVENEMENT_COMMANDE_CONFIRMEE,
                {
                    "commande_id": str(commande.id),
                    "client": commande.client,
                    "email": commande.email,
                    "seance_id": str(commande.seance_id),
                    "lignes": [
                        {"place_id": str(ligne.place_id), "montant": ligne.montant}
                        for ligne in commande.lignes
                    ],
                    "montant_total": commande.montant_total,
                },
            )
        )
    return replace(actuelle, statut=StatutCommande.CONFIRMEE, expire_le=commande.expire_le)


async def _lire_verrouillee(depot: DepotCommandes, commande: Commande) -> Commande:
    """La commande relue dans la transaction en cours, sa ligne verrouillée jusqu'à la fin du
    bloc : un seul changement de statut à la fois."""
    actuelle = await depot.lire_commande(commande.client, commande.id)
    if actuelle is None:  # pragma: no cover - la commande vient d'être lue
        raise CommandeIntrouvable(commande.id)
    return actuelle


def _deja_traitee(actuelle: Commande) -> Commande:
    """Commande sortie d'EN_ATTENTE par une requête concurrente : confirmée, elle est rendue
    telle quelle (aucun second ticketing.order.confirmed) ; sinon 409 ORDER_NOT_PENDING."""
    if actuelle.statut is StatutCommande.CONFIRMEE:
        return actuelle
    raise CommandeNonEnAttente(actuelle.id)


def _donnees_expiration(commande: Commande) -> dict[str, object]:
    """`data` de ticketing.order.expired sans `remboursement_du` : la commande, sa séance et
    toutes ses places (Billets ne libère que les verrous qu'elle détient, décision Q19)."""
    return {
        "commande_id": str(commande.id),
        "seance_id": str(commande.seance_id),
        "place_ids": [str(ligne.place_id) for ligne in commande.lignes],
    }


async def _expirer(
    depot: DepotCommandes,
    commande: Commande,
    paiements: ClientPaiements | None = None,
    *,
    echue_a: datetime | None = None,
) -> bool:
    """EXPIREE et ticketing.order.expired dans la même transaction, si elle est EN_ATTENTE ;
    renvoie vrai si cet appel l'a fait passer EXPIREE.

    `echue_a` (tâche d'expiration, H3 de BIL-010) : la transition n'a lieu que si `expire_le`,
    relu sous le verrou de ligne, est non NULL et `<= echue_a` ; un `payerCommande` qui vient de
    repousser l'échéance n'est donc jamais expiré pendant son appel à Paiements.

    `place_ids` : toutes les places de la commande ; Billets ne libère que les verrous qu'elle
    détient (décision Q19). Avec `paiements`, une commande déjà envoyée à Paiements voit son
    paiement **lu** (`lirePaiement`, jamais de `POST`, donc aucun débit possible) avant d'expirer,
    hors transaction : s'il est ACCEPTE, l'événement porte `remboursement_du: true` (review,
    point 3). Paiements injoignable : `ServiceIndisponible` (503), commande EN_ATTENTE.
    """
    remboursement_du = False
    if paiements is not None and commande.paiement_demande:
        paiement = await paiements.lire(commande.id)
        remboursement_du = paiement is not None and paiement.statut == PAIEMENT_ACCEPTE
    async with depot.transaction():
        actuelle = await _lire_verrouillee(depot, commande)
        if actuelle.statut is not StatutCommande.EN_ATTENTE:
            return False
        if echue_a is not None and (actuelle.expire_le is None or actuelle.expire_le > echue_a):
            return False
        await depot.changer_statut(commande.id, StatutCommande.EXPIREE)
        donnees = _donnees_expiration(commande)
        if remboursement_du:
            # Le remboursement lui-même relève d'un ticket ultérieur.
            journal.error("Commande %s expirée après un paiement accepté", commande.id)
            donnees["remboursement_du"] = True
        await depot.publier(Evenement.creer(EVENEMENT_COMMANDE_EXPIREE, donnees))
    return True
