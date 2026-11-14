"""Fixtures des tests unitaires de catalogue : dépôt en mémoire, horloge figée, jetons de test.

Sans base ni Keycloak ni Consul : l'application est assemblée par `creer_app`, le dépôt SQL est
remplacé par `DepotEnMemoire` (dependency_overrides) et le lifespan n'est pas démarré.

BIL-005 : `CacheEnMemoire` réalise le port `CacheCatalogue` avec une horloge pilotable
(`avancer`), et peut être rendu `injoignable` ou `lent` ; il remplace `obtenir_cache`.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import anyio
import httpx
import pytest
from fastapi import FastAPI

from catalogue.api.dependances import obtenir_cache, obtenir_depot, obtenir_maintenant
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
from catalogue.infra.base import BaseIndisponible, ErreurBase
from catalogue.infra.cache import CacheIndisponible
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
        # BIL-005 : pannes simulées, compteur de lectures et blocage de lister_evenements.
        self.injoignable = False
        self.erreur_imprevue = False
        self.lectures = 0
        # Posés par le test (un anyio.Event se crée dans la boucle) : lister_evenements signale
        # `liste_commencee`, puis attend `bloquer_listes`.
        self.bloquer_listes: anyio.Event | None = None
        self.liste_commencee: anyio.Event | None = None
        # BIL-011 : séances dont l'annulation a publié ticketing.show.cancelled, dans l'ordre.
        self.annulations_publiees: list[UUID] = []

    def _verifier(self) -> None:
        if self.injoignable:
            raise BaseIndisponible()
        if self.erreur_imprevue:
            raise ErreurBase()

    def _lire(self) -> None:
        # Compte chaque tentative de lecture, même quand la base est coupée.
        self.lectures += 1
        self._verifier()

    def renommer_evenement(self, evenement_id: UUID, nom: str) -> None:
        """Modification directe, sans passer par les routes (donc sans invalidation)."""
        self.evenements[evenement_id] = replace(self.evenements[evenement_id], nom=nom)

    def _tic(self) -> datetime:
        self._horloge += timedelta(minutes=1)
        return self._horloge

    def instantane(self) -> tuple[int, int, int]:
        return (len(self.evenements), len(self.lieux), len(self.seances))

    # --- semis directs ---------------------------------------------------------------------

    def semer_evenement(
        self,
        nom: str = "Concert de test",
        description: str = "Description synthétique",
        *,
        identifiant: UUID | None = None,
    ) -> Evenement:
        evenement = Evenement(
            id=identifiant or uuid4(), nom=nom, description=description, cree_le=self._tic()
        )
        self.evenements[evenement.id] = evenement
        return evenement

    def semer_lieu(
        self,
        nom: str = "Salle de test",
        adresse: str = "1 rue de l'Exemple",
        ville: str = "Villetest",
        *,
        identifiant: UUID | None = None,
    ) -> Lieu:
        lieu = Lieu(
            id=identifiant or uuid4(), nom=nom, adresse=adresse, ville=ville, cree_le=self._tic()
        )
        self.lieux[lieu.id] = lieu
        return lieu

    def semer_seance(
        self,
        evenement: Evenement,
        lieu: Lieu,
        debut: datetime | None = None,
        *,
        identifiant: UUID | None = None,
    ) -> Seance:
        seance = Seance(
            id=identifiant or uuid4(),
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
        self._verifier()
        return self.semer_evenement(nom, description)

    async def trouver_evenement(self, evenement_id: UUID) -> Evenement | None:
        self._lire()
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
        self._lire()
        # Liste lue avant le blocage : la lecture garde l'ancienne liste (course de Q14).
        retenus = self._filtrer(filtres)[decalage : decalage + limite]
        if self.bloquer_listes is not None:
            if self.liste_commencee is not None:
                self.liste_commencee.set()
            await self.bloquer_listes.wait()
        return retenus

    async def compter_evenements(self, filtres: FiltresEvenements) -> int:
        self._lire()
        return len(self._filtrer(filtres))

    async def ajouter_lieu(self, nom: str, adresse: str, ville: str) -> Lieu:
        self._verifier()
        return self.semer_lieu(nom, adresse, ville)

    async def trouver_lieu(self, lieu_id: UUID) -> Lieu | None:
        self._lire()
        return self.lieux.get(lieu_id)

    async def lister_lieux(self, decalage: int, limite: int) -> list[Lieu]:
        self._lire()
        ordonnes = sorted(self.lieux.values(), key=lambda lieu: (lieu.cree_le, lieu.id))
        return ordonnes[decalage : decalage + limite]

    async def compter_lieux(self) -> int:
        self._lire()
        return len(self.lieux)

    async def ajouter_seance(
        self, evenement: Evenement, lieu: Lieu, nouvelle: NouvelleSeance
    ) -> Seance:
        self._verifier()
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
        self._lire()
        return self.seances.get(seance_id)

    def _seances_de(self, evenement_id: UUID) -> list[Seance]:
        return sorted(
            (s for s in self.seances.values() if s.evenement_id == evenement_id),
            key=lambda s: (s.debut, s.id),
        )

    async def lister_seances(self, evenement_id: UUID, decalage: int, limite: int) -> list[Seance]:
        self._lire()
        return self._seances_de(evenement_id)[decalage : decalage + limite]

    async def compter_seances(self, evenement_id: UUID) -> int:
        self._lire()
        return len(self._seances_de(evenement_id))

    async def annuler_seance(self, seance: Seance) -> bool:
        """Passage conditionnel `annulee = false` → true ; chaque passage réussi « publie »
        ticketing.show.cancelled (noté dans `annulations_publiees`, BIL-011 H3)."""
        self._verifier()
        actuelle = self.seances.get(seance.id)
        if actuelle is None or actuelle.annulee:
            return False
        self.seances[seance.id] = replace(actuelle, annulee=True)
        self.annulations_publiees.append(seance.id)
        return True

    def semer_seance_annulee(self, seance: Seance) -> Seance:
        """Séance déjà annulée, posée sans passer par le domaine (aucun événement noté)."""
        annulee = replace(seance, annulee=True)
        self.seances[seance.id] = annulee
        return annulee


class CacheEnMemoire:
    """Double du port `CacheCatalogue` : expiration sur une horloge pilotée par `avancer`.

    `injoignable` : chaque appel lève `CacheIndisponible`. `lent` : chaque appel attend sans
    fin (Redis qui ne répond plus). `appels` compte les appels reçus, pannes comprises.
    """

    def __init__(self) -> None:
        self.instant = 0.0
        self._valeurs: dict[str, tuple[str, float]] = {}
        self.generations: dict[str, int] = {}
        self.injoignable = False
        self.lent = False
        self.appels = 0

    def avancer(self, secondes: float) -> None:
        self.instant += secondes

    def valeurs(self) -> dict[str, str]:
        """Valeurs encore vivantes à l'instant de l'horloge."""
        return {
            cle: valeur
            for cle, (valeur, expire_a) in self._valeurs.items()
            if self.instant < expire_a
        }

    async def _entrer(self) -> None:
        self.appels += 1
        if self.lent:
            await anyio.sleep_forever()
        if self.injoignable:
            raise CacheIndisponible()

    async def lire(self, cle: str) -> str | None:
        await self._entrer()
        return self.valeurs().get(cle)

    async def ecrire(self, cle: str, valeur: str, duree: float) -> None:
        await self._entrer()
        self._valeurs[cle] = (valeur, self.instant + duree)

    async def generation(self, famille: str) -> int:
        await self._entrer()
        return self.generations.get(famille, 0)

    async def nouvelle_generation(self, famille: str) -> int:
        await self._entrer()
        self.generations[famille] = self.generations.get(famille, 0) + 1
        return self.generations[famille]

    async def supprimer(self, *cles: str) -> None:
        await self._entrer()
        for cle in cles:
            self._valeurs.pop(cle, None)


@dataclass(frozen=True)
class Semis:
    """Événement E, lieu L et séance S semés, et les chemins des 7 lectures publiques."""

    evenement: Evenement
    lieu: Lieu
    seance: Seance
    lectures: dict[str, str]


def semer_catalogue(depot: DepotEnMemoire) -> Semis:
    evenement = depot.semer_evenement()
    lieu = depot.semer_lieu()
    seance = depot.semer_seance(evenement, lieu)
    lectures = {
        "listerEvenements": "/api/v1/events",
        "lireEvenement": f"/api/v1/events/{evenement.id}",
        "listerSeances": f"/api/v1/events/{evenement.id}/shows",
        "lireSeance": f"/api/v1/events/{evenement.id}/shows/{seance.id}",
        "lireSeanceParId": f"/api/v1/shows/{seance.id}",
        "listerLieux": "/api/v1/venues",
        "lireLieu": f"/api/v1/venues/{lieu.id}",
    }
    return Semis(evenement=evenement, lieu=lieu, seance=seance, lectures=lectures)


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


FabriqueApp = Callable[..., FastAPI]


@pytest.fixture
def fabrique_app(emetteur: EmetteurDeTest, depot: DepotEnMemoire) -> FabriqueApp:
    """Application sur le dépôt en mémoire ; `cache` remplace `obtenir_cache` s'il est donné,
    les autres arguments nommés vont à `Parametres` (delai_redis, durées du cache…)."""

    def fabriquer(cache: CacheEnMemoire | None = None, **reglages: Any) -> FastAPI:
        config = Parametres(
            database_url="postgresql+asyncpg://test@localhost/catalogue",
            instance=INSTANCE,
            consul_actif=False,
            **reglages,
        )
        application = creer_app(config, verificateur_jetons=emetteur.verificateur())

        def depot_de_test() -> DepotCatalogue:
            return depot

        application.dependency_overrides[obtenir_depot] = depot_de_test
        application.dependency_overrides[obtenir_maintenant] = lambda: MAINTENANT
        if cache is not None:
            application.dependency_overrides[obtenir_cache] = lambda: cache
        return application

    return fabriquer


@pytest.fixture
def app(fabrique_app: FabriqueApp) -> FastAPI:
    return fabrique_app()


@pytest.fixture
def cache() -> CacheEnMemoire:
    return CacheEnMemoire()


@pytest.fixture
def semis(depot: DepotEnMemoire) -> Semis:
    return semer_catalogue(depot)


@pytest.fixture
async def client(
    fabrique_app: FabriqueApp, cache: CacheEnMemoire
) -> AsyncIterator[httpx.AsyncClient]:
    """Client sans jeton sur l'application dont le cache est `CacheEnMemoire` (BIL-005)."""
    transport = httpx.ASGITransport(app=fabrique_app(cache))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


MiseEnCache = Callable[[str], Awaitable[httpx.Response]]


@pytest.fixture
def en_cache(client: httpx.AsyncClient, depot: DepotEnMemoire) -> MiseEnCache:
    """Lit `chemin` deux fois et vérifie que la seconde lecture vient du cache (pas du dépôt).

    Rend la seconde réponse, celle servie depuis le cache.
    """

    async def mettre_en_cache(chemin: str) -> httpx.Response:
        premiere = await client.get(chemin)
        assert premiere.status_code == 200, premiere.text
        avant = depot.lectures
        seconde = await client.get(chemin)
        assert seconde.status_code == 200, seconde.text
        assert depot.lectures == avant, f"{chemin} : la seconde lecture n'est pas servie du cache"
        return seconde

    return mettre_en_cache


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
