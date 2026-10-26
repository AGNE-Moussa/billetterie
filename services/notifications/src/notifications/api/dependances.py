"""Dépendances injectées dans les routes (équivalent de l'injection de Symfony)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.config import Parametres


def obtenir_parametres(requete: Request) -> Parametres:
    parametres: Parametres = requete.app.state.parametres
    return parametres


async def obtenir_session(requete: Request) -> AsyncIterator[AsyncSession]:
    """Une session par requête, fermée à la fin de la requête."""
    async with requete.app.state.sessions() as session:
        yield session


ParametresDep = Annotated[Parametres, Depends(obtenir_parametres)]
SessionDep = Annotated[AsyncSession, Depends(obtenir_session)]
