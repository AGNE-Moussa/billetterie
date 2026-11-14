"""Consommateurs d'événements du service billets.

`ticketing.show.scheduled` (décision Q5 de BIL-006) : crée les places de la séance, dans la
transaction qui inscrit le message dans `messages_traites` (commun.consommateurs). Un message
déjà traité est ignoré ; une séance déjà connue (autre message) ne crée aucun doublon
(`INSERT ... ON CONFLICT DO NOTHING`, décision Q18). Un `data` invalide lève une exception :
trois tentatives, puis `billets.show-scheduled.dlq`.

`ticketing.order.confirmed` (BIL-009) : émet les billets de la commande et publie un
`ticketing.ticket.issued` par billet, ou aucun billet et un `ticketing.ticket.rejected`
(décision Q1), dans la transaction de `messages_traites` ; puis, après le commit, supprime les
verrous Redis de la commande (décision Q4). File `billets.order-confirmed`.

`ticketing.order.expired` (BIL-010) : libère, dans le traitement, les verrous des places encore
détenus par la commande (décision Q3, H5). File `billets.order-expired`.

`ticketing.show.cancelled` (BIL-011) : inscrit la séance dans `seances_annulees` et passe ses
billets `ANNULE` (CA3, H4). File `billets.show-cancelled`.
"""

import functools
import logging
from datetime import UTC, datetime

from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from billets.domaine.annulation import (
    CONSOMMATEUR_SEANCE_ANNULEE,
    EVENEMENT_SEANCE_ANNULEE,
    annuler_seance,
)
from billets.domaine.emission import (
    CONSOMMATEUR_COMMANDE_CONFIRMEE,
    EVENEMENT_BILLET_EMIS,
    EVENEMENT_BILLETS_REFUSES,
    EVENEMENT_COMMANDE_CONFIRMEE,
    DonneesCommandeInvalides,
    commande_confirmee,
    donnees_billet_emis,
    donnees_refus,
    emettre_commande,
)
from billets.domaine.expiration import (
    CONSOMMATEUR_COMMANDE_EXPIREE,
    EVENEMENT_COMMANDE_EXPIREE,
    liberer_places_expirees,
)
from billets.domaine.places import (
    CONSOMMATEUR_SEANCE_PROGRAMMEE,
    EVENEMENT_SEANCE_PROGRAMMEE,
    places_de_la_seance,
)
from billets.domaine.verrous import MagasinVerrous, VerrouIndisponible
from billets.infra.depot import DepotAnnulationSql, DepotEmissionSql, DepotPlacesSql
from commun.consommateurs import consommateur_idempotent, traiter_une_fois
from commun.evenements import Evenement
from commun.outbox import publier_plus_tard

journal = logging.getLogger(__name__)


async def creer_places_de_la_seance(session: AsyncSession, evenement: Evenement) -> None:
    """Crée les places de la séance programmée (aucun doublon, aucune suppression)."""
    places = places_de_la_seance(evenement.data)
    await DepotPlacesSql(session).creer_places(places)
    # Lancé dans le bloc de corrélation du message : la ligne porte son correlation_id.
    journal.info(
        "Séance %s programmée : %d places reçues (message %s)",
        evenement.data.get("seance_id"),
        len(places),
        evenement.id,
    )


async def emettre_billets_de_la_commande(
    session: AsyncSession, evenement: Evenement, *, cle: str | None = None
) -> None:
    """Émet les billets de la commande confirmée (et leurs `ticket.issued`), ou publie un
    `ticket.rejected`, dans la transaction de la session.

    `cle` : clé de signature des QR ; None la lit dans `QR_CLE_SIGNATURE`.
    """
    issue = await emettre_commande(
        DepotEmissionSql(session), evenement.data, emis_le=datetime.now(UTC), cle=cle
    )
    commande_id = evenement.data.get("commande_id")
    if issue.refus is not None:
        await publier_plus_tard(
            session, Evenement.creer(EVENEMENT_BILLETS_REFUSES, donnees_refus(issue.refus))
        )
        journal.info(
            "Commande %s refusée (%s) : aucun billet émis, places %s (message %s)",
            commande_id,
            issue.refus.motif.value,
            [str(p) for p in issue.refus.place_ids],
            evenement.id,
        )
        return
    if not issue.billets:
        # Même commande publiée sous un autre identifiant (décision Q2).
        journal.info(
            "Billets de la commande %s déjà émis, rien de plus (message %s)",
            commande_id,
            evenement.id,
        )
        return
    for billet in issue.billets:
        await publier_plus_tard(
            session, Evenement.creer(EVENEMENT_BILLET_EMIS, donnees_billet_emis(billet))
        )
    journal.info(
        "Commande %s : %d billets émis (message %s)", commande_id, len(issue.billets), evenement.id
    )


async def liberer_verrous_de_la_commande(verrous: MagasinVerrous, evenement: Evenement) -> None:
    """Après le commit : supprime les verrous des places détenus par la commande (comparer puis
    supprimer). Un échec Redis est journalisé (`WARNING`), sans faire échouer le message."""
    try:
        commande = commande_confirmee(evenement.data)
    except DonneesCommandeInvalides:
        return
    for place_id in commande.place_ids:
        try:
            await verrous.liberer(commande.seance_id, place_id, commande.commande_id)
        except VerrouIndisponible:
            # Les verrous expireront d'eux-mêmes ; les places restent indisponibles par leur
            # billet. Inutile d'attendre Redis pour chaque place.
            journal.warning(
                "Verrous de la commande %s non supprimés : Redis injoignable (message %s)",
                commande.commande_id,
                evenement.id,
            )
            return


async def recevoir_commande_confirmee(
    sessions: async_sessionmaker[AsyncSession],
    verrous: MagasinVerrous,
    evenement: Evenement,
    *,
    cle: str | None = None,
) -> None:
    """Une livraison de ticketing.order.confirmed : traitement idempotent dans sa transaction
    (`messages_traites`), puis suppression des verrous de la commande."""
    await traiter_une_fois(
        sessions,
        CONSOMMATEUR_COMMANDE_CONFIRMEE,
        functools.partial(emettre_billets_de_la_commande, cle=cle),
        evenement,
        functools.partial(liberer_verrous_de_la_commande, verrous),
    )


async def liberer_places_de_la_commande_expiree(
    verrous: MagasinVerrous, session: AsyncSession, evenement: Evenement
) -> None:
    """Libère, dans le traitement (décision Q3 de BIL-010), les verrous des places détenus par
    la commande expirée ; aucune écriture en base hors `messages_traites`.

    Données invalides ou Redis injoignable : l'exception remonte (nouvel essai, puis DLQ).
    """
    await liberer_places_expirees(verrous, evenement.data)
    journal.info(
        "Commande %s expirée : verrous de ses places libérés (message %s)",
        evenement.data.get("commande_id"),
        evenement.id,
    )


async def annuler_billets_de_la_seance(session: AsyncSession, evenement: Evenement) -> None:
    """Traitement de ticketing.show.cancelled (BIL-011, CA3) : inscrit la séance annulée et
    passe ses billets `ANNULE`, dans la transaction de `messages_traites`."""
    annules = await annuler_seance(
        DepotAnnulationSql(session), evenement.data, annulee_le=datetime.now(UTC)
    )
    journal.info(
        "Séance %s annulée : %d billets annulés (message %s)",
        evenement.data.get("seance_id"),
        annules,
        evenement.id,
    )


def abonner_consommateurs(
    broker: RabbitBroker,
    sessions: async_sessionmaker[AsyncSession],
    verrous: MagasinVerrous,
    cle_qr: str | None = None,
) -> None:
    """Abonne les traitements du service au broker, avant `commun.consommateurs.messagerie`.

    `cle_qr` : clé de signature des QR (configuration) ; None la lit dans `QR_CLE_SIGNATURE`.
    """
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_SEANCE_PROGRAMMEE,
        type_evenement=EVENEMENT_SEANCE_PROGRAMMEE,
    )(creer_places_de_la_seance)
    # Suppression des verrous après le commit (décision Q4).
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_COMMANDE_CONFIRMEE,
        type_evenement=EVENEMENT_COMMANDE_CONFIRMEE,
        apres_commit=functools.partial(liberer_verrous_de_la_commande, verrous),
    )(functools.partial(emettre_billets_de_la_commande, cle=cle_qr))
    # Libération dans le traitement : une panne Redis repart en nouvel essai (décision Q3 de
    # BIL-010).
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_COMMANDE_EXPIREE,
        type_evenement=EVENEMENT_COMMANDE_EXPIREE,
    )(functools.partial(liberer_places_de_la_commande_expiree, verrous))
    # Billets de la séance annulée (BIL-011, CA3), sous le verrou exclusif de la séance (Q3).
    consommateur_idempotent(
        broker,
        sessions,
        nom=CONSOMMATEUR_SEANCE_ANNULEE,
        type_evenement=EVENEMENT_SEANCE_ANNULEE,
    )(annuler_billets_de_la_seance)
