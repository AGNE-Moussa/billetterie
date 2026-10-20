"""Dépôt des echos sur PostgreSQL."""

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echo.domaine.echos import Echo, EchoDejaExistant
from echo.infra.base import EchoLigne


class DepotEchosSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ajouter(self, message: str) -> Echo:
        requete = insert(EchoLigne).values(message=message).returning(EchoLigne.cree_le)
        try:
            cree_le = (await self._session.execute(requete)).scalar_one()
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
