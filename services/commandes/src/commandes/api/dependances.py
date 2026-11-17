"""Dépendances injectées dans les routes (équivalent de l'injection de Symfony).

Les tests unitaires remplacent `obtenir_depot`, `obtenir_catalogue`, `obtenir_billets`,
`obtenir_paiements` et `obtenir_maintenant` par `dependency_overrides` (dépôt en mémoire,
clients sur `httpx.MockTransport`, horloge figée).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from commandes.config import Parametres
from commandes.domaine.commandes import DepotCommandes
from commandes.domaine.services import ClientBillets, ClientCatalogue, ClientPaiements
from commandes.infra.clients import CIBLE_BILLETS, CIBLE_CATALOGUE, CIBLE_PAIEMENTS
from commandes.infra.depot import DepotCommandesSql
from commun.http import ServiceIndisponible


def obtenir_parametres(requete: Request) -> Parametres:
    parametres: Parametres = requete.app.state.parametres
    return parametres


async def obtenir_session(requete: Request) -> AsyncIterator[AsyncSession]:
    """Une session par requête, fermée à la fin de la requête."""
    async with requete.app.state.sessions() as session:
        yield session


def obtenir_depot(
    requete: Request, session: Annotated[AsyncSession, Depends(obtenir_session)]
) -> DepotCommandes:
    # Moteur dédié aux clés d'idempotence, créé par le lifespan (review BIL-008, point 4).
    moteur_cles: AsyncEngine | None = getattr(requete.app.state, "moteur_cles", None)
    return DepotCommandesSql(session, moteur_cles)


def obtenir_catalogue(requete: Request) -> ClientCatalogue:
    """Client de Catalogue créé au démarrage ; absent : 503 SERVICE_INDISPONIBLE."""
    client: ClientCatalogue | None = getattr(requete.app.state, "catalogue", None)
    if client is None:
        raise ServiceIndisponible(CIBLE_CATALOGUE)
    return client


def obtenir_billets(requete: Request) -> ClientBillets:
    """Client de Billets créé au démarrage ; absent : 503 SERVICE_INDISPONIBLE."""
    client: ClientBillets | None = getattr(requete.app.state, "billets", None)
    if client is None:
        raise ServiceIndisponible(CIBLE_BILLETS)
    return client


def obtenir_paiements(requete: Request) -> ClientPaiements:
    """Client de Paiements créé au démarrage ; absent : 503 SERVICE_INDISPONIBLE."""
    client: ClientPaiements | None = getattr(requete.app.state, "paiements", None)
    if client is None:
        raise ServiceIndisponible(CIBLE_PAIEMENTS)
    return client


def obtenir_maintenant() -> datetime:
    """Instant de la requête ; remplacé par `dependency_overrides` pour figer l'horloge."""
    return datetime.now(UTC)


ParametresDep = Annotated[Parametres, Depends(obtenir_parametres)]
SessionDep = Annotated[AsyncSession, Depends(obtenir_session)]
DepotDep = Annotated[DepotCommandes, Depends(obtenir_depot)]
CatalogueDep = Annotated[ClientCatalogue, Depends(obtenir_catalogue)]
BilletsDep = Annotated[ClientBillets, Depends(obtenir_billets)]
PaiementsDep = Annotated[ClientPaiements, Depends(obtenir_paiements)]
MaintenantDep = Annotated[datetime, Depends(obtenir_maintenant)]
