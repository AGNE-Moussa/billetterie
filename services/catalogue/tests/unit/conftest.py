"""Fixtures des tests unitaires de catalogue : dépôt en mémoire, horloge figée, jetons de test.

Sans base ni Keycloak ni Consul : l'application est assemblée par `creer_app`, le dépôt SQL est
remplacé par `DepotEnMemoire` (dependency_overrides) et le lifespan n'est pas démarré.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from catalogue.api.dependances import obtenir_depot, obtenir_maintenant
from catalogue.config import Parametres
from catalogue.domaine.catalogue import (
    Categorie,
    DepotCatalogue,
    Evenement,
    FiltresEvenements,
    Lieu,
    NouvelleSeance,
    Rang,
    Seance,
)
from catalogue.principal import creer_app
from commun.faux_jetons import EmetteurDeTest

INSTANCE = "catalogue-test"
# Instant de la requête vu par le domaine (MaintenantDep remplacé).
MAINTENANT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
ORIGINE = datetime(2026, 10, 1, tzinfo=UTC)


class DepotEnMemoire:
    """Dépôt en mémoire conforme à DepotCatalogue ; `semer_*` pose des données sans le domaine."""

    def __init__(self) -> None:
        self.evenements: dict[UUID, Evenement] = {}
        self.lieux: dict[UUID, Lieu] = {}
        self.seances: dict[UUID, Seance] = {}
        self._horloge = ORIGINE

    def _tic(self) -> datetime:
        self._horloge += timedelta(minutes=1)
        return self._horloge

    def instantane(self) -> tuple[int, int, int]:
        return (len(self.evenements), len(self.lieux), len(self.seances))

    # --- semis directs ---------------------------------------------------------------------

    def semer_evenement(
        self, nom: str = "Concert de test", description: str = "Description synthétique"
    ) -> Evenement:
        evenement = Evenement(id=uuid4(), nom=nom, description=description, cree_le=self._tic())
        self.evenements[evenement.id] = evenement
        return evenement

    def semer_lieu(
        self,
        nom: str = "Salle de test",
        adresse: str = "1 rue de l'Exemple",
        ville: str = "Villetest",
    ) -> Lieu:
        lieu = Lieu(id=uuid4(), nom=nom, adresse=adresse, ville=ville, cree_le=self._tic())
        self.lieux[lieu.id] = lieu
        return lieu

    def semer_seance(
        self, evenement: Evenement, lieu: Lieu, debut: datetime | None = None
    ) -> Seance:
        seance = Seance(
            id=uuid4(),
            evenement_id=evenement.id,
            lieu_id=lieu.id,
            debut=debut or MAINTENANT + timedelta(days=30),
            annulee=False,
            categories=[
                Categorie(
                    id=uuid4(),
                    nom="Fosse",
                    prix=4500,
                    rangs=[Rang(rang="A", nombre_places=10), Rang(rang="B", nombre_places=12)],
                )
            ],
        )
        self.seances[seance.id] = seance
        return seance

    # --- DepotCatalogue --------------------------------------------------------------------

    async def ajouter_evenement(self, nom: str, description: str) -> Evenement:
        return self.semer_evenement(nom, description)

    async def trouver_evenement(self, evenement_id: UUID) -> Evenement | None:
        return self.evenements.get(evenement_id)

    def _filtrer(self, filtres: FiltresEvenements) -> list[Evenement]:
        retenus = []
        for evenement in sorted(self.evenements.values(), key=lambda e: (e.cree_le, e.id)):
            if filtres.q is not None:
                motif = filtres.q.casefold()
                if motif not in (evenement.nom + " " + evenement.description).casefold():
                    continue
            if filtres.ville is not None or filtres.du is not None or filtres.au is not None:
                seances = [
                    s
                    for s in self.seances.values()
                    if s.evenement_id == evenement.id
                    and (
                        filtres.ville is None
                        or self.lieux[s.lieu_id].ville.casefold() == filtres.ville.casefold()
                    )
                    and (filtres.du is None or s.debut >= filtres.du)
                    and (filtres.au is None or s.debut <= filtres.au)
                ]
                if not seances:
                    continue
            retenus.append(evenement)
        return retenus

    async def lister_evenements(
        self, filtres: FiltresEvenements, decalage: int, limite: int
    ) -> list[Evenement]:
        return self._filtrer(filtres)[decalage : decalage + limite]

    async def compter_evenements(self, filtres: FiltresEvenements) -> int:
        return len(self._filtrer(filtres))

    async def ajouter_lieu(self, nom: str, adresse: str, ville: str) -> Lieu:
        return self.semer_lieu(nom, adresse, ville)

    async def trouver_lieu(self, lieu_id: UUID) -> Lieu | None:
        return self.lieux.get(lieu_id)

    async def lister_lieux(self, decalage: int, limite: int) -> list[Lieu]:
        ordonnes = sorted(self.lieux.values(), key=lambda lieu: (lieu.cree_le, lieu.id))
        return ordonnes[decalage : decalage + limite]

    async def compter_lieux(self) -> int:
        return len(self.lieux)

    async def ajouter_seance(
        self, evenement: Evenement, lieu: Lieu, nouvelle: NouvelleSeance
    ) -> Seance:
        seance = Seance(
            id=uuid4(),
            evenement_id=evenement.id,
            lieu_id=lieu.id,
            debut=nouvelle.debut,
            annulee=False,
            categories=[
                Categorie(id=uuid4(), nom=c.nom, prix=c.prix, rangs=list(c.rangs))
                for c in nouvelle.categories
            ],
        )
        self.seances[seance.id] = seance
        return seance

    async def trouver_seance(self, seance_id: UUID) -> Seance | None:
        return self.seances.get(seance_id)

    def _seances_de(self, evenement_id: UUID) -> list[Seance]:
        return sorted(
            (s for s in self.seances.values() if s.evenement_id == evenement_id),
            key=lambda s: (s.debut, s.id),
        )

    async def lister_seances(self, evenement_id: UUID, decalage: int, limite: int) -> list[Seance]:
        return self._seances_de(evenement_id)[decalage : decalage + limite]

    async def compter_seances(self, evenement_id: UUID) -> int:
        return len(self._seances_de(evenement_id))


def corps_seance(lieu_id: UUID | str, debut: datetime | None = None) -> dict[str, Any]:
    """Séance commune du plan : « Fosse » à 4500 centimes, rangs A (10) et B (12)."""
    return {
        "lieu_id": str(lieu_id),
        "debut": (debut or MAINTENANT + timedelta(days=30)).isoformat(),
        "categories": [
            {
                "nom": "Fosse",
                "prix": 4500,
                "rangs": [{"rang": "A", "nombre_places": 10}, {"rang": "B", "nombre_places": 12}],
            }
        ],
    }


CORPS_EVENEMENT = {"nom": "Concert de test", "description": "Description synthétique"}
CORPS_LIEU = {"nom": "Salle de test", "adresse": "1 rue de l'Exemple", "ville": "Villetest"}


# Le mode importlib de pytest interdit `from conftest import ...` : constantes et fabriques sont
# servies en fixtures.


@pytest.fixture
def maintenant() -> datetime:
    return MAINTENANT


@pytest.fixture
def seance_valide() -> Any:
    return corps_seance


@pytest.fixture
def evenement_valide() -> dict[str, str]:
    return dict(CORPS_EVENEMENT)


@pytest.fixture
def lieu_valide() -> dict[str, str]:
    return dict(CORPS_LIEU)


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


@pytest.fixture
def depot() -> DepotEnMemoire:
    return DepotEnMemoire()


@pytest.fixture
def app(emetteur: EmetteurDeTest, depot: DepotEnMemoire) -> FastAPI:
    config = Parametres(
        database_url="postgresql+asyncpg://test@localhost/catalogue",
        instance=INSTANCE,
        consul_actif=False,
    )
    application = creer_app(config, verificateur_jetons=emetteur.verificateur())

    def depot_de_test() -> DepotCatalogue:
        return depot

    application.dependency_overrides[obtenir_depot] = depot_de_test
    application.dependency_overrides[obtenir_maintenant] = lambda: MAINTENANT
    return application


@pytest.fixture
async def anonyme(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Client sans jeton ; sans lifespan : ni base ni Consul ne sont démarrés."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def entetes_admin(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(roles=["admin"], scopes=["events:read", "events:write"])


@pytest.fixture
def entetes_client(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(roles=["customer"], scopes=["events:read"])


@pytest.fixture
def entetes_revendeur(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(roles=["partner"], scopes=["events:read"], client="revendeur-test")


@pytest.fixture
def entetes_service(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(client="services", scopes=["seats:lock"])
