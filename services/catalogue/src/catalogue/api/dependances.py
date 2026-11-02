"""Dépendances injectées dans les routes (équivalent de l'injection de Symfony)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from catalogue.api.cache_lectures import LecturesEnCache
from catalogue.config import Parametres
from catalogue.domaine.cache import CacheCatalogue
from catalogue.domaine.catalogue import DepotCatalogue
from catalogue.infra.depot import DepotCatalogueSql


def obtenir_parametres(requete: Request) -> Parametres:
    parametres: Parametres = requete.app.state.parametres
    return parametres


async def obtenir_session(requete: Request) -> AsyncIterator[AsyncSession]:
    """Une session par requête, fermée à la fin de la requête."""
    async with requete.app.state.sessions() as session:
        yield session


def obtenir_depot(session: Annotated[AsyncSession, Depends(obtenir_session)]) -> DepotCatalogue:
    return DepotCatalogueSql(session)


def obtenir_cache(requete: Request) -> CacheCatalogue | None:
    """Cache des lectures, ou None sans `redis_url` (pas de cache, comme dans BIL-004).

    Remplacé par `dependency_overrides` dans les tests unitaires (double en mémoire).
    """
    cache: CacheCatalogue | None = getattr(requete.app.state, "cache", None)
    return cache


def obtenir_lectures(
    cache: Annotated[CacheCatalogue | None, Depends(obtenir_cache)],
    parametres: Annotated[Parametres, Depends(obtenir_parametres)],
) -> LecturesEnCache:
    """Cache-aside des lectures, une instance par requête (réglages de `Parametres`)."""
    return LecturesEnCache(
        cache,
        delai=parametres.delai_redis,
        duree_fraiche=parametres.cache_duree_fraiche,
        duree_secours=parametres.cache_duree_secours,
    )


def obtenir_maintenant() -> datetime:
    """Instant de la requête ; remplacé par `dependency_overrides` pour figer l'horloge."""
    return datetime.now(UTC)


ParametresDep = Annotated[Parametres, Depends(obtenir_parametres)]
SessionDep = Annotated[AsyncSession, Depends(obtenir_session)]
DepotDep = Annotated[DepotCatalogue, Depends(obtenir_depot)]
MaintenantDep = Annotated[datetime, Depends(obtenir_maintenant)]
LecturesDep = Annotated[LecturesEnCache, Depends(obtenir_lectures)]
