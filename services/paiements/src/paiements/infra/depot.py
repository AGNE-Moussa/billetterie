"""Dépôt SQL des paiements (réalisation de `domaine.paiements.DepotPaiements`).

Toute méthode qui touche la base traduit une base injoignable (connexion refusée, délai
dépassé, connexion coupée) en `BaseIndisponible` : 503 BASE_INDISPONIBLE, sans détail technique
(comme billets). Un autre refus de la base est journalisé et remonte (500).
"""

import functools
import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy import exc as sa_exc
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from paiements.domaine.paiements import Paiement, StatutPaiement
from paiements.infra.base import BaseIndisponible, PaiementLigne, SeanceAnnuleeLigne

journal = logging.getLogger(__name__)

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
            journal.exception("Erreur de la base de paiements")
            raise

    return enveloppe


def _paiement(ligne: PaiementLigne) -> Paiement:
    return Paiement(
        id=ligne.id,
        commande_id=ligne.commande_id,
        seance_id=ligne.seance_id,
        montant=ligne.montant,
        statut=StatutPaiement(ligne.statut),
        cree_le=ligne.cree_le,
    )


class DepotPaiementsSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @_base_requise
    async def lire_par_commande(self, commande_id: uuid.UUID) -> Paiement | None:
        ligne = await self._session.scalar(
            select(PaiementLigne).where(PaiementLigne.commande_id == commande_id)
        )
        return None if ligne is None else _paiement(ligne)

    @_base_requise
    async def seance_annulee(self, seance_id: uuid.UUID) -> bool:
        requete = select(exists().where(SeanceAnnuleeLigne.seance_id == seance_id))
        return bool(await self._session.scalar(requete))

    @_base_requise
    async def inserer_ou_relire(self, paiement: Paiement) -> Paiement:
        # ON CONFLICT DO NOTHING attend la transaction concurrente de même commande_id, puis
        # n'insère rien ; la relecture suivante (nouvel instantané, READ COMMITTED) voit le
        # paiement gagnant (décision Q21).
        await self._session.execute(
            insert(PaiementLigne)
            .values(
                id=paiement.id,
                commande_id=paiement.commande_id,
                seance_id=paiement.seance_id,
                montant=paiement.montant,
                statut=paiement.statut.value,
                cree_le=paiement.cree_le,
            )
            .on_conflict_do_nothing(constraint="uq_paiements_commande_id")
        )
        await self._session.commit()
        ligne = await self._session.scalar(
            select(PaiementLigne)
            .where(PaiementLigne.commande_id == paiement.commande_id)
            .execution_options(populate_existing=True)
        )
        if ligne is None:  # pragma: no cover - la ligne vient d'être insérée ou existait
            raise RuntimeError("Paiement introuvable après insertion")
        return _paiement(ligne)
