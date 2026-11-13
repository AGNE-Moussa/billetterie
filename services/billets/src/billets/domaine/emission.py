"""Émission des billets d'une commande confirmée : règles métier, sans SQLAlchemy ni Redis.

`ticketing.order.confirmed` donne un billet `EMIS` par ligne de la commande (une place
« vendue » = un billet sur la place, H1). Émission tout ou rien par commande (décision Q1) : une
place déjà vendue ou une séance annulée ne donne aucun billet, mais un
`ticketing.ticket.rejected`.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from billets.domaine.qr import contenu_qr

# Consommé pour émettre les billets (rules/billets-qr.md).
EVENEMENT_COMMANDE_CONFIRMEE = "ticketing.order.confirmed"
# File durable du consommateur (messages_traites.consommateur, DLQ billets.order-confirmed.dlq).
CONSOMMATEUR_COMMANDE_CONFIRMEE = "billets.order-confirmed"
# Publiés par l'outbox.
EVENEMENT_BILLET_EMIS = "ticketing.ticket.issued"
EVENEMENT_BILLETS_REFUSES = "ticketing.ticket.rejected"

STATUT_EMIS = "EMIS"


class MotifRefus(StrEnum):
    """Motif de `ticketing.ticket.rejected` (docs/evenements)."""

    PLACE_DEJA_VENDUE = "PLACE_DEJA_VENDUE"
    SEANCE_ANNULEE = "SEANCE_ANNULEE"


@dataclass(frozen=True)
class CommandeConfirmee:
    """`data` de ticketing.order.confirmed, utile à Billets."""

    commande_id: UUID
    client: str
    seance_id: UUID
    place_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class NouveauBillet:
    id: UUID
    commande_id: UUID
    client: str
    seance_id: UUID
    place_id: UUID
    statut: str
    qr_code: str
    emis_le: datetime


@dataclass(frozen=True)
class RefusCommande:
    """Charge de `ticketing.ticket.rejected`."""

    commande_id: UUID
    seance_id: UUID
    place_ids: tuple[UUID, ...]
    motif: MotifRefus


class DonneesCommandeInvalides(ValueError):
    """`data` de ticketing.order.confirmed inexploitable : le message part en file d'erreur
    après trois tentatives (commun.consommateurs)."""


class DepotEmission(Protocol):
    """Accès aux billets et aux séances annulées, dans la transaction du consommateur."""

    async def seance_annulee(self, seance_id: UUID) -> bool:
        """Vrai si la séance figure dans `seances_annulees`."""
        ...

    async def places_de_la_commande_emises(
        self, commande_id: UUID, seance_id: UUID, place_ids: Sequence[UUID]
    ) -> set[UUID]:
        """Parmi `place_ids`, celles qui portent déjà un billet de cette commande (Q2)."""
        ...

    async def emettre(self, billets: Sequence[NouveauBillet]) -> set[UUID]:
        """Insère tous les billets, tout ou rien, dans la transaction en cours.

        Renvoie l'ensemble vide si tous sont insérés ; sinon les places en conflit sur
        `uq_billets_place`, et aucun billet de l'appel ne reste inséré.
        """
        ...


def commande_confirmee(data: dict[str, Any]) -> CommandeConfirmee:
    """Lit `data` de ticketing.order.confirmed ; lève `DonneesCommandeInvalides`."""
    try:
        commande_id = UUID(str(data["commande_id"]))
        seance_id = UUID(str(data["seance_id"]))
        client = data["client"]
        place_ids = tuple(UUID(str(ligne["place_id"])) for ligne in data["lignes"])
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesCommandeInvalides(f"Commande confirmée invalide : {erreur!r}") from erreur
    if not isinstance(client, str) or not client:
        raise DonneesCommandeInvalides("Commande confirmée invalide : client absent")
    if not place_ids:
        raise DonneesCommandeInvalides("Commande confirmée invalide : aucune ligne")
    if len(set(place_ids)) != len(place_ids):
        raise DonneesCommandeInvalides("Commande confirmée invalide : place en double")
    return CommandeConfirmee(
        commande_id=commande_id, client=client, seance_id=seance_id, place_ids=place_ids
    )


def billets_a_emettre(
    data: dict[str, Any], *, emis_le: datetime, cle: str | None = None
) -> list[NouveauBillet]:
    """Un billet `EMIS` par ligne de la commande, avec son QR signé (`cle` : voir `qr.signer`).

    Lève `DonneesCommandeInvalides` si `data` est inexploitable.
    """
    commande = commande_confirmee(data)
    billets = []
    for place_id in commande.place_ids:
        billet_id = uuid4()
        billets.append(
            NouveauBillet(
                id=billet_id,
                commande_id=commande.commande_id,
                client=commande.client,
                seance_id=commande.seance_id,
                place_id=place_id,
                statut=STATUT_EMIS,
                qr_code=contenu_qr(billet_id, cle),
                emis_le=emis_le,
            )
        )
    return billets


def rejet_de_commande(
    data: dict[str, Any], *, places_en_conflit: Collection[UUID], seance_annulee: bool
) -> RefusCommande:
    """Refus de la commande : `SEANCE_ANNULEE` avec toutes ses places, ou
    `PLACE_DEJA_VENDUE` avec les places en conflit (décision Q1)."""
    commande = commande_confirmee(data)
    if seance_annulee:
        motif, places = MotifRefus.SEANCE_ANNULEE, commande.place_ids
    else:
        # Ordre des lignes de la commande conservé.
        motif = MotifRefus.PLACE_DEJA_VENDUE
        places = tuple(p for p in commande.place_ids if p in set(places_en_conflit))
    return RefusCommande(
        commande_id=commande.commande_id,
        seance_id=commande.seance_id,
        place_ids=places,
        motif=motif,
    )


def donnees_billet_emis(billet: NouveauBillet) -> dict[str, Any]:
    """`data` de ticketing.ticket.issued v1."""
    return {
        "billet_id": str(billet.id),
        "commande_id": str(billet.commande_id),
        "seance_id": str(billet.seance_id),
        "place_id": str(billet.place_id),
        "qr_code": billet.qr_code,
        "emis_le": billet.emis_le.isoformat(),
    }


def donnees_refus(refus: RefusCommande) -> dict[str, Any]:
    """`data` de ticketing.ticket.rejected v1."""
    return {
        "commande_id": str(refus.commande_id),
        "seance_id": str(refus.seance_id),
        "place_ids": [str(p) for p in refus.place_ids],
        "motif": refus.motif.value,
    }


@dataclass(frozen=True)
class IssueEmission:
    """Résultat de l'émission d'une commande : billets émis, refus, ou rien (déjà émise)."""

    billets: tuple[NouveauBillet, ...] = ()
    refus: RefusCommande | None = None


async def emettre_commande(
    depot: DepotEmission, data: dict[str, Any], *, emis_le: datetime, cle: str | None = None
) -> IssueEmission:
    """Émission tout ou rien d'une commande confirmée (décisions Q1, Q2).

    Jamais de « lire puis écrire » sur les places : l'insertion elle-même, arbitrée par
    `uq_billets_place`, dit quelles places sont déjà prises. Les places en conflit qui portent
    déjà un billet de la même commande (nouvelle publication sous un autre identifiant) ne sont
    pas un refus : la commande est déjà émise.

    « Déjà émise » est testé avant « séance annulée » : une commande émise puis republiée après
    l'annulation ne publie pas de `ticket.rejected` (sinon double remboursement possible). La
    lecture ne porte que sur les billets de la commande elle-même, jamais sur la disponibilité
    des places ; deux livraisons simultanées sont arbitrées après l'insertion (plus bas).
    """
    billets = billets_a_emettre(data, emis_le=emis_le, cle=cle)
    commande = commande_confirmee(data)
    deja_emises = await depot.places_de_la_commande_emises(
        commande.commande_id, commande.seance_id, sorted(commande.place_ids, key=str)
    )
    if deja_emises == set(commande.place_ids):
        return IssueEmission()
    if await depot.seance_annulee(commande.seance_id):
        return IssueEmission(
            refus=rejet_de_commande(data, places_en_conflit=(), seance_annulee=True)
        )
    conflits = await depot.emettre(billets)
    if not conflits:
        return IssueEmission(billets=tuple(billets))
    deja_emises = await depot.places_de_la_commande_emises(
        commande.commande_id, commande.seance_id, sorted(conflits)
    )
    autres = conflits - deja_emises
    if not autres:
        return IssueEmission()
    return IssueEmission(
        refus=rejet_de_commande(data, places_en_conflit=autres, seance_annulee=False)
    )
