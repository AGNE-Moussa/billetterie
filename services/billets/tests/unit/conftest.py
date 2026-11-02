"""Fixtures des tests unitaires de billets : dépôt et verrous en mémoire, horloge pilotable.

Sans base, ni Redis, ni Keycloak, ni Consul : l'application est assemblée par `creer_app`, le
lifespan n'est pas démarré, et `dependency_overrides` remplace le dépôt SQL (`DepotEnMemoire`),
le magasin Redis (`VerrousEnMemoire`) et l'horloge de la requête (`Horloge`).

`VerrousEnMemoire` réalise le port `MagasinVerrous` sur l'horloge partagée : chaque méthode
s'exécute sans `await` intermédiaire, donc de façon atomique, comme le script Lua.
"""

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from billets.api.dependances import obtenir_depot, obtenir_maintenant, obtenir_verrous
from billets.config import Parametres
from billets.domaine.places import DepotPlaces, NouvellePlace, PageResultat, Place
from billets.domaine.verrous import MagasinVerrous, VerrouIndisponible, cle_verrou
from billets.principal import creer_app
from commun.faux_jetons import EmetteurDeTest

INSTANCE = "billets-test"
MAINTENANT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
# URL synthétique : jamais contactée (lifespan non démarré, magasin remplacé).
URL_BASE = "postgresql+asyncpg://test@127.0.0.1:5432/billets"
URL_REDIS = "redis://127.0.0.1:6379/0"


class Horloge:
    """Instant partagé par le magasin de verrous et `obtenir_maintenant`."""

    def __init__(self, depart: datetime = MAINTENANT) -> None:
        self.maintenant = depart

    def avancer(self, secondes: float) -> None:
        self.maintenant += timedelta(seconds=secondes)


class VerrousEnMemoire:
    """Double du port `MagasinVerrous` : clé `place:<seance>:<place>`, valeur `commande_id`.

    `injoignable` : chaque appel lève `VerrouIndisponible`. `appels` compte les appels reçus.
    """

    def __init__(self, horloge: Horloge) -> None:
        self.horloge = horloge
        self._cles: dict[str, tuple[str, datetime]] = {}
        self.injoignable = False
        self.appels = 0

    def _entrer(self) -> None:
        self.appels += 1
        if self.injoignable:
            raise VerrouIndisponible()

    def _vivant(self, cle: str) -> tuple[str, datetime] | None:
        valeur = self._cles.get(cle)
        if valeur is None or valeur[1] <= self.horloge.maintenant:
            self._cles.pop(cle, None)
            return None
        return valeur

    def _restant_ms(self, expire: datetime) -> int:
        return int((expire - self.horloge.maintenant) / timedelta(milliseconds=1))

    # --- inspection directe (sans compter d'appel) ---------------------------------------------

    def cles(self) -> dict[str, str]:
        """Clés vivantes à l'instant de l'horloge, et leur valeur."""
        return {cle: v[0] for cle in list(self._cles) if (v := self._vivant(cle)) is not None}

    def detenteur(self, seance_id: UUID, place_id: UUID) -> str | None:
        vivant = self._vivant(cle_verrou(seance_id, place_id))
        return None if vivant is None else vivant[0]

    def expiration(self, seance_id: UUID, place_id: UUID) -> datetime | None:
        vivant = self._vivant(cle_verrou(seance_id, place_id))
        return None if vivant is None else vivant[1]

    def semer(self, seance_id: UUID, place_id: UUID, commande_id: UUID, secondes: float) -> None:
        """Pose un verrou sans passer par la route."""
        expire = self.horloge.maintenant + timedelta(seconds=secondes)
        self._cles[cle_verrou(seance_id, place_id)] = (str(commande_id), expire)

    # --- MagasinVerrous -------------------------------------------------------------------------

    async def poser(
        self, seance_id: UUID, place_id: UUID, commande_id: UUID, duree_ms: int
    ) -> int | None:
        self._entrer()
        cle = cle_verrou(seance_id, place_id)
        vivant = self._vivant(cle)
        demandee = self.horloge.maintenant + timedelta(milliseconds=duree_ms)
        if vivant is None:
            self._cles[cle] = (str(commande_id), demandee)
            return duree_ms
        valeur, expire = vivant
        if valeur != str(commande_id):
            return None
        # Ne jamais raccourcir (décision Q15).
        nouvelle = max(expire, demandee)
        self._cles[cle] = (valeur, nouvelle)
        return self._restant_ms(nouvelle)

    async def confirmer(
        self, seance_id: UUID, place_id: UUID, commande_id: UUID, duree_ms: int
    ) -> int | None:
        self._entrer()
        cle = cle_verrou(seance_id, place_id)
        vivant = self._vivant(cle)
        if vivant is None or vivant[0] != str(commande_id):
            return None
        self._cles[cle] = (vivant[0], self.horloge.maintenant + timedelta(milliseconds=duree_ms))
        return duree_ms

    async def liberer(self, seance_id: UUID, place_id: UUID, commande_id: UUID) -> bool:
        self._entrer()
        cle = cle_verrou(seance_id, place_id)
        vivant = self._vivant(cle)
        if vivant is None or vivant[0] != str(commande_id):
            return False
        del self._cles[cle]
        return True

    async def verrouillees(self, seance_id: UUID, place_ids: Sequence[UUID]) -> set[UUID]:
        self._entrer()
        return {p for p in place_ids if self._vivant(cle_verrou(seance_id, p)) is not None}

    async def fermer(self) -> None:
        return None


class DepotEnMemoire:
    """Dépôt en mémoire conforme à `DepotPlaces` ; `semer_*` pose des données sans le domaine."""

    def __init__(self) -> None:
        self.places: dict[UUID, Place] = {}
        # Billets (seance_id, place_id), quel que soit leur statut (décision Q14).
        self.billets: set[tuple[UUID, UUID]] = set()

    def semer_place(self, seance_id: UUID, rang: str, numero: int, categorie_id: UUID) -> Place:
        place = Place(
            id=uuid4(), seance_id=seance_id, rang=rang, numero=numero, categorie_id=categorie_id
        )
        self.places[place.id] = place
        return place

    def semer_billet(self, place: Place) -> None:
        self.billets.add((place.seance_id, place.id))

    def place(self, seance_id: UUID, rang: str, numero: int) -> Place:
        return next(
            p
            for p in self.places.values()
            if (p.seance_id, p.rang, p.numero) == (seance_id, rang, numero)
        )

    # --- DepotPlaces ----------------------------------------------------------------------------

    async def lire_place(self, place_id: UUID) -> Place | None:
        return self.places.get(place_id)

    async def billet_existe(self, seance_id: UUID, place_id: UUID) -> bool:
        return (seance_id, place_id) in self.billets

    async def places_vendues(self, seance_id: UUID, place_ids: Sequence[UUID]) -> set[UUID]:
        return {p for p in place_ids if (seance_id, p) in self.billets}

    async def lister_places(self, seance_id: UUID, page: int, size: int) -> PageResultat[Place]:
        # Tri binaire du rang (COLLATE "C"), puis numéro, puis identifiant (Q19).
        ordonnees = sorted(
            (p for p in self.places.values() if p.seance_id == seance_id),
            key=lambda p: (p.rang.encode(), p.numero, str(p.id)),
        )
        debut = (page - 1) * size
        return PageResultat(elements=ordonnees[debut : debut + size], total=len(ordonnees))

    async def creer_places(self, places: Sequence[NouvellePlace]) -> None:
        connues = {(p.seance_id, p.rang, p.numero) for p in self.places.values()}
        for nouvelle in places:
            if (nouvelle.seance_id, nouvelle.rang, nouvelle.numero) not in connues:
                self.semer_place(
                    nouvelle.seance_id, nouvelle.rang, nouvelle.numero, nouvelle.categorie_id
                )
                connues.add((nouvelle.seance_id, nouvelle.rang, nouvelle.numero))


@dataclass
class Seance:
    """Séance commune du plan : Fosse (A × 10, B × 12) et Balcon (C × 5), 27 places."""

    id: UUID
    fosse: UUID
    balcon: UUID
    places: dict[str, Place] = field(default_factory=dict)

    def __getitem__(self, nom: str) -> Place:
        """`seance["A1"]` : la place du rang A, numéro 1."""
        return self.places[nom]


# Rangs dans l'ordre de création ; le tri est l'affaire du dépôt.
RANGS_COMMUNS = (("B", 12, "fosse"), ("A", 10, "fosse"), ("C", 5, "balcon"))


def semer_seance(depot: DepotEnMemoire) -> Seance:
    seance = Seance(id=uuid4(), fosse=uuid4(), balcon=uuid4())
    for rang, nombre, categorie in RANGS_COMMUNS:
        categorie_id = seance.fosse if categorie == "fosse" else seance.balcon
        for numero in range(1, nombre + 1):
            seance.places[f"{rang}{numero}"] = depot.semer_place(
                seance.id, rang, numero, categorie_id
            )
    return seance


def donnees_seance_programmee(seance_id: UUID, fosse: UUID, balcon: UUID) -> dict[str, Any]:
    """`data` de ticketing.show.scheduled du plan (schéma dans docs/evenements/)."""
    return {
        "seance_id": str(seance_id),
        "evenement_id": str(uuid4()),
        "evenement_nom": "Concert de test",
        "lieu_id": str(uuid4()),
        "lieu_nom": "Salle de test",
        "ville": "Villetest",
        "debut": (MAINTENANT + timedelta(days=30)).isoformat(),
        "categories": [
            {
                "categorie_id": str(fosse),
                "nom": "Fosse",
                "prix": 4500,
                "rangs": [{"rang": "A", "nombre_places": 10}, {"rang": "B", "nombre_places": 12}],
            },
            {
                "categorie_id": str(balcon),
                "nom": "Balcon",
                "prix": 3000,
                "rangs": [{"rang": "C", "nombre_places": 5}],
            },
        ],
    }


# Le mode importlib de pytest interdit `from conftest import ...` : tout est servi en fixtures.


@pytest.fixture
def horloge() -> Horloge:
    return Horloge()


@pytest.fixture
def depot() -> DepotEnMemoire:
    return DepotEnMemoire()


@pytest.fixture
def verrous(horloge: Horloge) -> VerrousEnMemoire:
    return VerrousEnMemoire(horloge)


@pytest.fixture
def seance(depot: DepotEnMemoire) -> Seance:
    return semer_seance(depot)


@pytest.fixture
def donnees_seance() -> Callable[[UUID, UUID, UUID], dict[str, Any]]:
    return donnees_seance_programmee


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


FabriqueApp = Callable[..., FastAPI]


@pytest.fixture
def fabrique_app(
    emetteur: EmetteurDeTest,
    depot: DepotEnMemoire,
    verrous: VerrousEnMemoire,
    horloge: Horloge,
) -> FabriqueApp:
    """Application sur le dépôt et les verrous en mémoire ; les arguments nommés vont à
    `Parametres` (durées, délais) et remplacent l'environnement."""

    def fabriquer(**reglages: Any) -> FastAPI:
        reglages.setdefault("database_url", URL_BASE)
        reglages.setdefault("redis_url", URL_REDIS)
        config = Parametres(instance=INSTANCE, consul_actif=False, **reglages)
        application = creer_app(config, verificateur_jetons=emetteur.verificateur())

        def depot_de_test() -> DepotPlaces:
            return depot

        def verrous_de_test() -> MagasinVerrous:
            return verrous

        application.dependency_overrides[obtenir_depot] = depot_de_test
        application.dependency_overrides[obtenir_verrous] = verrous_de_test
        application.dependency_overrides[obtenir_maintenant] = lambda: horloge.maintenant
        return application

    return fabriquer


@pytest.fixture
def app(fabrique_app: FabriqueApp) -> FastAPI:
    return fabrique_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Client sans jeton par défaut ; sans lifespan : ni base, ni Redis, ni Consul."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def entetes_service(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(client="services", scopes=["seats:lock"])


@pytest.fixture
def entetes_service_sans_scope(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(client="services", scopes=["echos:read"])


SCOPES_CLIENT = ["events:read", "orders:read", "orders:write", "tickets:read"]


@pytest.fixture
def entetes_client(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(
        roles=["customer"], scopes=SCOPES_CLIENT, sujet="client.test@exemple.test"
    )


@pytest.fixture
def entetes_revendeur(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(roles=["partner"], scopes=SCOPES_CLIENT, client="revendeur-test")


@pytest.fixture
def entetes_admin(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(roles=["admin"], scopes=["events:read", "events:write"])
