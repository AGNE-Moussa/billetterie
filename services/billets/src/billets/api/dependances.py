"""Dépendances injectées dans les routes (équivalent de l'injection de Symfony).

Les tests unitaires remplacent `obtenir_depot`, `obtenir_verrous` et `obtenir_maintenant` par
`dependency_overrides` (dépôt en mémoire, magasin de verrous en mémoire, horloge figée).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from billets.config import Parametres
from billets.domaine.consultation import DepotBillets
from billets.domaine.places import DepotPlaces, DureesVerrou
from billets.domaine.verrous import MagasinVerrous, VerrouIndisponible
from billets.infra.depot import DepotBilletsSql, DepotPlacesSql


def obtenir_parametres(requete: Request) -> Parametres:
    parametres: Parametres = requete.app.state.parametres
    return parametres


async def obtenir_session(requete: Request) -> AsyncIterator[AsyncSession]:
    """Une session par requête, fermée à la fin de la requête."""
    async with requete.app.state.sessions() as session:
        yield session


def obtenir_depot(session: Annotated[AsyncSession, Depends(obtenir_session)]) -> DepotPlaces:
    return DepotPlacesSql(session)


def obtenir_depot_billets(
    session: Annotated[AsyncSession, Depends(obtenir_session)],
) -> DepotBillets:
    return DepotBilletsSql(session)


def obtenir_verrous(requete: Request) -> MagasinVerrous:
    """Magasin de verrous de l'application (créé au démarrage) ; absent : 503."""
    verrous: MagasinVerrous | None = getattr(requete.app.state, "verrous", None)
    if verrous is None:
        raise VerrouIndisponible()
    return verrous


def obtenir_durees(
    parametres: Annotated[Parametres, Depends(obtenir_parametres)],
) -> DureesVerrou:
    return DureesVerrou(
        reservation=parametres.duree_verrou_reservation,
        confirmation=parametres.duree_verrou_confirmation,
    )


def obtenir_maintenant() -> datetime:
    """Instant de la requête ; remplacé par `dependency_overrides` pour figer l'horloge."""
    return datetime.now(UTC)


ParametresDep = Annotated[Parametres, Depends(obtenir_parametres)]
SessionDep = Annotated[AsyncSession, Depends(obtenir_session)]
DepotDep = Annotated[DepotPlaces, Depends(obtenir_depot)]
DepotBilletsDep = Annotated[DepotBillets, Depends(obtenir_depot_billets)]
VerrousDep = Annotated[MagasinVerrous, Depends(obtenir_verrous)]
DureesDep = Annotated[DureesVerrou, Depends(obtenir_durees)]
MaintenantDep = Annotated[datetime, Depends(obtenir_maintenant)]
