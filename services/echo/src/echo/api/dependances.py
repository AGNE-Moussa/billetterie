"""Dépendances injectées dans les routes (équivalent de l'injection de Symfony)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from echo.config import Parametres
from echo.domaine.echos import DepotEchos
from echo.infra.depot import DepotEchosSql


def obtenir_parametres(requete: Request) -> Parametres:
    parametres: Parametres = requete.app.state.parametres
    return parametres


async def obtenir_session(requete: Request) -> AsyncIterator[AsyncSession]:
    """Une session par requête, fermée à la fin de la requête."""
    async with requete.app.state.sessions() as session:
        yield session


def obtenir_depot(session: Annotated[AsyncSession, Depends(obtenir_session)]) -> DepotEchos:
    return DepotEchosSql(session)


ParametresDep = Annotated[Parametres, Depends(obtenir_parametres)]
SessionDep = Annotated[AsyncSession, Depends(obtenir_session)]
DepotDep = Annotated[DepotEchos, Depends(obtenir_depot)]
