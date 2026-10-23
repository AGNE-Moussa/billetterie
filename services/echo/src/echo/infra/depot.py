"""Dépôt des echos sur PostgreSQL."""

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from commun.evenements import Evenement
from commun.outbox import publier_plus_tard
from echo.domaine.echos import EVENEMENT_ECHO_CREE, Echo, EchoDejaExistant
from echo.infra.base import EchoLigne


class DepotEchosSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ajouter(self, message: str) -> Echo:
        requete = insert(EchoLigne).values(message=message).returning(EchoLigne.cree_le)
        try:
            cree_le = (await self._session.execute(requete)).scalar_one()
            # Même transaction que l'écriture : l'événement part si, et seulement si, l'echo
            # est enregistré.
            await publier_plus_tard(
                self._session,
                Evenement.creer(
                    EVENEMENT_ECHO_CREE, {"message": message, "cree_le": cree_le.isoformat()}
                ),
            )
            await self._session.commit()
        except IntegrityError as erreur:
            # La contrainte unique tranche, même si deux instances écrivent en même temps.
            await self._session.rollback()
            raise EchoDejaExistant(message) from erreur
        return Echo(message=message, cree_le=cree_le)

    async def trouver(self, message: str) -> Echo | None:
        requete = select(EchoLigne).where(EchoLigne.message == message)
        ligne = (await self._session.execute(requete)).scalar_one_or_none()
        if ligne is None:
            return None
        return Echo(message=ligne.message, cree_le=ligne.cree_le)

    async def lister(self, decalage: int, limite: int) -> list[Echo]:
        # Ordre total et stable : cree_le décroissant, puis message (unique) croissant, pour
        # qu'aucun echo ne soit répété ni perdu d'une page à l'autre.
        requete = (
            select(EchoLigne)
            .order_by(EchoLigne.cree_le.desc(), EchoLigne.message.asc())
            .offset(decalage)
            .limit(limite)
        )
        lignes = (await self._session.execute(requete)).scalars().all()
        return [Echo(message=ligne.message, cree_le=ligne.cree_le) for ligne in lignes]

    async def compter(self) -> int:
        requete = select(func.count()).select_from(EchoLigne)
        return (await self._session.execute(requete)).scalar_one()
