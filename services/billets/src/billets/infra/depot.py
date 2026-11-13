"""Dépôts SQL des places et des billets (réalisations de `domaine.places.DepotPlaces` et de
`domaine.emission.DepotEmission`).

Toute méthode qui touche la base traduit une base injoignable (connexion refusée, délai
dépassé, connexion coupée) en `BaseIndisponible` : 503 BASE_INDISPONIBLE, sans détail technique
(comme le catalogue). Un autre refus de la base est journalisé et remonte (500).
"""

import functools
import logging
import uuid
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from sqlalchemy import delete, exists, func, select
from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from billets.domaine.emission import NouveauBillet
from billets.domaine.places import NouvellePlace, PageResultat, Place
from billets.infra.base import BaseIndisponible, BilletLigne, PlaceLigne, SeanceAnnuleeLigne

journal = logging.getLogger(__name__)

# Lignes par INSERT de places : 5 paramètres par ligne, soit 5 000 paramètres, bien sous la
# limite de 32 767 d'asyncpg.
PLACES_PAR_LOT = 1000

# Base injoignable : TimeoutError et ConnectionRefusedError sont des OSError.
ERREURS_CONNEXION: tuple[type[BaseException], ...] = (
    OSError,
    sa_exc.OperationalError,
    sa_exc.InterfaceError,
    sa_exc.TimeoutError,
)


def _base_requise[**P, R](
    methode: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    @functools.wraps(methode)
    async def enveloppe(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await methode(*args, **kwargs)
        except ERREURS_CONNEXION as erreur:
            raise BaseIndisponible() from erreur
        except sa_exc.DBAPIError as erreur:
            if erreur.connection_invalidated:
                raise BaseIndisponible() from erreur
            journal.exception("Erreur de la base de billets")
            raise

    return enveloppe


def _place(ligne: PlaceLigne) -> Place:
    return Place(
        id=ligne.id,
        seance_id=ligne.seance_id,
        rang=ligne.rang,
        numero=ligne.numero,
        categorie_id=ligne.categorie_id,
    )


class DepotPlacesSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @_base_requise
    async def lire_place(self, place_id: uuid.UUID) -> Place | None:
        ligne = await self._session.get(PlaceLigne, place_id)
        return None if ligne is None else _place(ligne)

    @_base_requise
    async def billet_existe(self, seance_id: uuid.UUID, place_id: uuid.UUID) -> bool:
        # Tout billet rend la place indisponible, quel que soit son statut (décision Q14).
        requete = select(
            exists().where(BilletLigne.seance_id == seance_id, BilletLigne.place_id == place_id)
        )
        return bool(await self._session.scalar(requete))

    @_base_requise
    async def places_vendues(
        self, seance_id: uuid.UUID, place_ids: Sequence[uuid.UUID]
    ) -> set[uuid.UUID]:
        if not place_ids:
            return set()
        requete = select(BilletLigne.place_id).where(
            BilletLigne.seance_id == seance_id, BilletLigne.place_id.in_(place_ids)
        )
        return set((await self._session.scalars(requete)).all())

    @_base_requise
    async def lister_places(
        self, seance_id: uuid.UUID, page: int, size: int
    ) -> PageResultat[Place]:
        total = await self._session.scalar(
            select(func.count()).select_from(PlaceLigne).where(PlaceLigne.seance_id == seance_id)
        )
        # Rang en tri binaire (COLLATE "C", indépendant de la locale de la base), puis numéro,
        # puis identifiant pour un ordre stable (décision Q19).
        requete = (
            select(PlaceLigne)
            .where(PlaceLigne.seance_id == seance_id)
            .order_by(PlaceLigne.rang.collate("C"), PlaceLigne.numero, PlaceLigne.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        lignes = (await self._session.scalars(requete)).all()
        return PageResultat(elements=[_place(ligne) for ligne in lignes], total=int(total or 0))

    @_base_requise
    async def creer_places(self, places: Sequence[NouvellePlace]) -> None:
        # Un INSERT par lot de PLACES_PAR_LOT lignes : asyncpg refuse plus de 32 767
        # paramètres par requête (5 par place). Tous les lots passent par la même session,
        # donc dans la transaction du consommateur (avec messages_traites) : tout ou rien.
        # L'ordre reçu est conservé, lot après lot.
        for debut in range(0, len(places), PLACES_PAR_LOT):
            lot = places[debut : debut + PLACES_PAR_LOT]
            # Une place déjà connue (même séance, rang, numéro) est ignorée : nouvelle
            # publication de la séance ou messages simultanés, sans erreur ni doublon (Q18).
            requete = (
                insert(PlaceLigne)
                .values(
                    [
                        {
                            "id": uuid.uuid4(),
                            "seance_id": place.seance_id,
                            "rang": place.rang,
                            "numero": place.numero,
                            "categorie_id": place.categorie_id,
                        }
                        for place in lot
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_places_seance_rang_numero")
            )
            await self._session.execute(requete)


class DepotEmissionSql:
    """Réalisation de `domaine.emission.DepotEmission`, dans la session du consommateur."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @_base_requise
    async def seance_annulee(self, seance_id: uuid.UUID) -> bool:
        requete = select(exists().where(SeanceAnnuleeLigne.seance_id == seance_id))
        return bool(await self._session.scalar(requete))

    @_base_requise
    async def places_de_la_commande_emises(
        self, commande_id: uuid.UUID, seance_id: uuid.UUID, place_ids: Sequence[uuid.UUID]
    ) -> set[uuid.UUID]:
        if not place_ids:
            return set()
        requete = select(BilletLigne.place_id).where(
            BilletLigne.commande_id == commande_id,
            BilletLigne.seance_id == seance_id,
            BilletLigne.place_id.in_(place_ids),
        )
        return set((await self._session.scalars(requete)).all())

    @_base_requise
    async def emettre(self, billets: Sequence[NouveauBillet]) -> set[uuid.UUID]:
        if not billets:
            return set()
        # Ordre stable (par place) : deux commandes simultanées qui se disputent plusieurs
        # places les prennent dans le même ordre, sans interblocage.
        ordonnes = sorted(billets, key=lambda b: str(b.place_id))
        # ON CONFLICT DO NOTHING sur uq_billets_place : une place prise (même par une
        # transaction concurrente, attendue jusqu'à son commit) n'est pas insérée, sans
        # exception. Une place inconnue (fk_billets_place) lève IntegrityError : l'exception
        # remonte (nouvel essai puis DLQ, décision Q5).
        requete = (
            insert(BilletLigne)
            .values(
                [
                    {
                        "id": billet.id,
                        "commande_id": billet.commande_id,
                        "client": billet.client,
                        "seance_id": billet.seance_id,
                        "place_id": billet.place_id,
                        "statut": billet.statut,
                        "qr_code": billet.qr_code,
                        "emis_le": billet.emis_le,
                    }
                    for billet in ordonnes
                ]
            )
            .on_conflict_do_nothing(constraint="uq_billets_place")
            .returning(BilletLigne.place_id)
        )
        inserees = set((await self._session.scalars(requete)).all())
        conflits = {billet.place_id for billet in billets} - inserees
        if conflits and inserees:
            # Tout ou rien pour la commande (décision Q1) : les billets tout juste insérés sont
            # retirés dans la même transaction. Pas de SAVEPOINT : ses lignes porteraient l'xmin
            # d'une sous-transaction, et ROLLBACK TO SAVEPOINT en ouvre une nouvelle pour les
            # écritures suivantes (ticket.rejected) ; billets, outbox et messages_traites
            # doivent appartenir à une seule et même transaction.
            await self._session.execute(
                delete(BilletLigne).where(
                    BilletLigne.id.in_([b.id for b in billets if b.place_id in inserees])
                )
            )
        return conflits
