"""Fixtures des tests unitaires de paiements : dépôt en mémoire, horloge figée (plan BIL-008).

Sans base, ni Keycloak, ni Consul : l'application est assemblée par `creer_app`, le lifespan
n'est pas démarré, et `dependency_overrides` remplace le dépôt SQL (`DepotEnMemoire`, double du
port `DepotPaiements`) et l'horloge de la requête.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from commun.evenements import Evenement
from commun.faux_jetons import EmetteurDeTest
from paiements.api.dependances import obtenir_depot, obtenir_maintenant
from paiements.config import Parametres
from paiements.domaine.paiements import DepotPaiements, Paiement, StatutPaiement
from paiements.principal import creer_app

MAINTENANT = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
# URL synthétique : jamais contactée (lifespan non démarré, dépôt remplacé).
URL_BASE = "postgresql+asyncpg://test@127.0.0.1:5432/paiements"


class DepotEnMemoire:
    """Double des ports `DepotPaiements` et `remboursements.DepotRemboursements` (BIL-011) :
    un paiement au plus par commande.

    `verrous_seance` note la séance de chaque verrou consultatif demandé ; `evenements` garde
    les événements rangés dans l'outbox, dans l'ordre.
    """

    def __init__(self) -> None:
        self.paiements: dict[UUID, Paiement] = {}
        self.seances_annulees: set[UUID] = set()
        self.verrous_seance: list[UUID] = []
        self.evenements: list[Evenement] = []

    def semer(
        self,
        seance_id: UUID,
        statut: StatutPaiement = StatutPaiement.ACCEPTE,
        *,
        montant: int = 4500,
        commande_id: UUID | None = None,
    ) -> Paiement:
        """Pose un paiement sans passer par le domaine."""
        paiement = Paiement(
            id=uuid4(),
            commande_id=commande_id or uuid4(),
            seance_id=seance_id,
            montant=montant,
            statut=statut,
            cree_le=MAINTENANT,
        )
        self.paiements[paiement.commande_id] = paiement
        return paiement

    def statut(self, paiement: Paiement) -> StatutPaiement:
        return self.paiements[paiement.commande_id].statut

    # --- DepotPaiements -------------------------------------------------------------------------

    async def lire_par_commande(self, commande_id: UUID) -> Paiement | None:
        return self.paiements.get(commande_id)

    async def verrouiller_seance(self, seance_id: UUID) -> None:
        self.verrous_seance.append(seance_id)

    async def seance_annulee(self, seance_id: UUID) -> bool:
        return seance_id in self.seances_annulees

    async def inserer_ou_relire(self, paiement: Paiement) -> Paiement:
        return self.paiements.setdefault(paiement.commande_id, paiement)

    # --- DepotRemboursements --------------------------------------------------------------------

    async def inscrire_seance_annulee(self, seance_id: UUID, annulee_le: datetime) -> bool:
        if seance_id in self.seances_annulees:
            return False
        self.seances_annulees.add(seance_id)
        return True

    async def rembourser_paiements_de_la_seance(self, seance_id: UUID) -> list[Paiement]:
        rembourses = []
        for commande_id, paiement in list(self.paiements.items()):
            if paiement.seance_id == seance_id and paiement.statut is StatutPaiement.ACCEPTE:
                self.paiements[commande_id] = replace(paiement, statut=StatutPaiement.REMBOURSE)
                rembourses.append(self.paiements[commande_id])
        return rembourses

    async def rembourser_paiement_de_la_commande(self, commande_id: UUID) -> Paiement | None:
        paiement = self.paiements.get(commande_id)
        if paiement is None or paiement.statut is not StatutPaiement.ACCEPTE:
            return None
        self.paiements[commande_id] = replace(paiement, statut=StatutPaiement.REMBOURSE)
        return self.paiements[commande_id]

    async def publier(self, evenement: Evenement) -> None:
        self.evenements.append(evenement)


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
