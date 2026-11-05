"""Fixtures des tests unitaires de paiements : dépôt en mémoire, horloge figée (plan BIL-008).

Sans base, ni Keycloak, ni Consul : l'application est assemblée par `creer_app`, le lifespan
n'est pas démarré, et `dependency_overrides` remplace le dépôt SQL (`DepotEnMemoire`, double du
port `DepotPaiements`) et l'horloge de la requête.
"""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from commun.faux_jetons import EmetteurDeTest
from paiements.api.dependances import obtenir_depot, obtenir_maintenant
from paiements.config import Parametres
from paiements.domaine.paiements import DepotPaiements, Paiement
from paiements.principal import creer_app

MAINTENANT = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
# URL synthétique : jamais contactée (lifespan non démarré, dépôt remplacé).
URL_BASE = "postgresql+asyncpg://test@127.0.0.1:5432/paiements"


class DepotEnMemoire:
    """Double du port `DepotPaiements` : un paiement au plus par commande."""

    def __init__(self) -> None:
        self.paiements: dict[UUID, Paiement] = {}
        self.seances_annulees: set[UUID] = set()

    async def lire_par_commande(self, commande_id: UUID) -> Paiement | None:
        return self.paiements.get(commande_id)

    async def seance_annulee(self, seance_id: UUID) -> bool:
        return seance_id in self.seances_annulees

    async def inserer_ou_relire(self, paiement: Paiement) -> Paiement:
        return self.paiements.setdefault(paiement.commande_id, paiement)


@pytest.fixture
def depot() -> DepotEnMemoire:
    return DepotEnMemoire()


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


@pytest.fixture
def app(emetteur: EmetteurDeTest, depot: DepotEnMemoire) -> FastAPI:
    config = Parametres(database_url=URL_BASE, instance="paiements-test", consul_actif=False)
    application = creer_app(config, verificateur_jetons=emetteur.verificateur())

    def depot_de_test() -> DepotPaiements:
        return depot

    application.dependency_overrides[obtenir_depot] = depot_de_test
    application.dependency_overrides[obtenir_maintenant] = lambda: MAINTENANT
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def entetes_service(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(client="services", scopes=["seats:lock", "payments:write"])


@pytest.fixture
def requete_paiement() -> Callable[..., tuple[dict[str, Any], dict[str, str]]]:
    """Corps `PaiementCreation` et en-tête `Idempotency-Key` (= `commande_id`)."""

    def fabriquer(
        *,
        commande_id: UUID | None = None,
        seance_id: UUID | None = None,
        montant: int = 4500,
        carte: str = "4242424242424242",
    ) -> tuple[dict[str, Any], dict[str, str]]:
        commande = commande_id or uuid4()
        corps = {
            "commande_id": str(commande),
            "seance_id": str(seance_id or uuid4()),
            "montant": montant,
            "carte_test": carte,
        }
        return corps, {"Idempotency-Key": str(commande)}

    return fabriquer
