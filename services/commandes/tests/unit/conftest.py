"""Fixtures des tests unitaires de commandes (plan BIL-008, « Doubles et fixtures »).

Sans base, ni Keycloak, ni Consul, ni gateway : l'application est assemblée par `creer_app`, le
lifespan n'est pas démarré, et `dependency_overrides` remplace :

- `obtenir_depot` : `DepotEnMemoire`, double du port `DepotCommandes` (transaction annulée si
  le bloc lève, événements gardés seulement à la validation) ;
- `obtenir_catalogue`, `obtenir_billets`, `obtenir_paiements` : les vrais clients
  `ClientCatalogueHttp`, `ClientBilletsHttp`, `ClientPaiementsHttp` sur un
  `commun.http.ClientService` dont le transport est un `httpx.MockTransport` : Catalogue,
  Billets et Paiements y sont simulés en mémoire et chaque requête reçue est notée (méthode,
  chemin, corps, en-têtes) dans un journal commun, dans l'ordre d'arrivée ;
- `obtenir_maintenant` : l'horloge pilotable `Horloge`.

Le jeton de service vient d'un `JetonService` réel servi par un faux Keycloak (MockTransport) qui
rend un jeton `EmetteurDeTest` (`client="services"`, scopes `seats:lock payments:write`).
Chaque `ClientService` a son propre disjoncteur et n'attend pas entre deux tentatives.
"""

import json
import re
import secrets
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from commandes.api.dependances import (
    obtenir_billets,
    obtenir_catalogue,
    obtenir_depot,
    obtenir_maintenant,
    obtenir_paiements,
)
from commandes.config import Parametres
from commandes.domaine.commandes import (
    Commande,
    DepotCommandes,
    LigneCommande,
    PageResultat,
    StatutCommande,
)
from commandes.domaine.services import ClientBillets, ClientCatalogue, ClientPaiements
from commandes.infra.clients import (
    CIBLE_BILLETS,
    CIBLE_CATALOGUE,
    CIBLE_PAIEMENTS,
    ClientBilletsHttp,
    ClientCatalogueHttp,
    ClientPaiementsHttp,
)
from commandes.principal import creer_app
from commun.evenements import Evenement
from commun.faux_jetons import EmetteurDeTest
from commun.http import ClientService, Disjoncteur, JetonService

MAINTENANT = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
# URL synthétiques : jamais contactées (lifespan non démarré, transports simulés).
URL_BASE = "postgresql+asyncpg://test@127.0.0.1:5432/commandes"
URL_GATEWAY = "http://gateway-de-test"
URL_REDIS = "redis://127.0.0.1:6379/0"
URL_JETON = "http://keycloak-de-test/token"
CARTE_REFUSEE = "4000000000000002"
DUREE_RESERVATION = 600
DUREE_CONFIRMATION = 3600
SCOPES_SERVICE = ["seats:lock", "payments:write"]
SCOPES_COMMANDES = ["orders:read", "orders:write"]


class Horloge:
    """Instant partagé par `obtenir_maintenant` et le faux Billets."""

    def __init__(self, depart: datetime = MAINTENANT) -> None:
        self.maintenant = depart

    def avancer(self, secondes: float) -> None:
        self.maintenant += timedelta(seconds=secondes)


# --- Journal des appels sortants ----------------------------------------------------------------


@dataclass(frozen=True)
class Appel:
    cible: str
    methode: str
    chemin: str
    corps: dict[str, Any] | None
    entetes: dict[str, str]


class Journal:
    """Appels reçus par les faux services, dans l'ordre d'arrivée."""

    def __init__(self) -> None:
        self.appels: list[Appel] = []

    def noter(self, cible: str, requete: httpx.Request) -> Appel:
        contenu = requete.content
        corps = json.loads(contenu) if contenu else None
        appel = Appel(
            cible=cible,
            methode=requete.method,
            chemin=requete.url.path,
            corps=corps,
            entetes={cle.lower(): valeur for cle, valeur in requete.headers.items()},
        )
        self.appels.append(appel)
        return appel

    def de(self, cible: str) -> list[Appel]:
        return [a for a in self.appels if a.cible == cible]


def _probleme(statut: int, code: str) -> httpx.Response:
    return httpx.Response(
        statut,
        json={"type": "about:blank", "title": code, "status": statut, "detail": code, "code": code},
        headers={"content-type": "application/problem+json"},
    )


# --- Faux services ------------------------------------------------------------------------------


class FauxKeycloak:
    """Point de jeton : rend un jeton de service signé par `EmetteurDeTest`."""

    def __init__(self, emetteur: EmetteurDeTest) -> None:
        self.emetteur = emetteur
        self.en_panne = False
        self.jetons_emis: list[str] = []

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        if self.en_panne:
            raise httpx.ConnectError("Keycloak injoignable (test)", request=requete)
        jeton = self.emetteur.jeton(client="services", scopes=SCOPES_SERVICE)
        self.jetons_emis.append(jeton)
        return httpx.Response(200, json={"access_token": jeton, "expires_in": 300})


class FauxCatalogue:
    """`GET /api/v1/shows/{seance_id}` (lireSeanceParId) : séances en mémoire."""

    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self.seances: dict[UUID, dict[str, Any]] = {}
        self.en_panne = False

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.journal.noter(CIBLE_CATALOGUE, requete)
        if self.en_panne:
            return _probleme(503, "SERVICE_INDISPONIBLE")
        trouve = re.fullmatch(r"/api/v1/shows/([0-9a-f-]+)", requete.url.path)
        if requete.method != "GET" or trouve is None:
            return _probleme(404, "RESSOURCE_INTROUVABLE")
        seance = self.seances.get(UUID(trouve.group(1)))
        if seance is None:
            return _probleme(404, "SHOW_NOT_FOUND")
        return httpx.Response(200, json=seance)


class FauxBillets:
    """`PUT /api/v1/seats/{place_id}/lock` (verrouillerPlace) : verrous en mémoire.

    Mêmes règles que Billets : place inconnue ou d'une autre séance : 404 SEAT_NOT_FOUND ;
    place vendue, verrouillée par une autre commande, ou confirmation sans détenir le verrou :
    409 SEAT_ALREADY_TAKEN. `panne_reservation` / `panne_confirmation` : 503 sur les appels
    `confirmation` faux / vrai.
    """

    def __init__(self, journal: Journal, horloge: Horloge) -> None:
        self.journal = journal
        self.horloge = horloge
        # place_id : (seance_id, categorie_id)
        self.places: dict[UUID, tuple[UUID, UUID]] = {}
        self.verrous: dict[UUID, UUID] = {}
        self.vendues: set[UUID] = set()
        self.panne_reservation = False
        self.panne_confirmation = False

    def semer_verrou(self, place_id: UUID, commande_id: UUID) -> None:
        self.verrous[place_id] = commande_id

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        appel = self.journal.noter(CIBLE_BILLETS, requete)
        trouve = re.fullmatch(r"/api/v1/seats/([0-9a-f-]+)/lock", requete.url.path)
        if requete.method != "PUT" or trouve is None or appel.corps is None:
            return _probleme(404, "RESSOURCE_INTROUVABLE")
        confirmation = bool(appel.corps.get("confirmation", False))
        if (confirmation and self.panne_confirmation) or (
            not confirmation and self.panne_reservation
        ):
            return _probleme(503, "VERROU_INDISPONIBLE")
        place_id = UUID(trouve.group(1))
        seance_id = UUID(appel.corps["seance_id"])
        commande_id = UUID(appel.corps["commande_id"])
        place = self.places.get(place_id)
        if place is None or place[0] != seance_id:
            return _probleme(404, "SEAT_NOT_FOUND")
        detenteur = self.verrous.get(place_id)
        if place_id in self.vendues or (detenteur is not None and detenteur != commande_id):
            return _probleme(409, "SEAT_ALREADY_TAKEN")
        if confirmation and detenteur != commande_id:
            return _probleme(409, "SEAT_ALREADY_TAKEN")
        self.verrous[place_id] = commande_id
        duree = DUREE_CONFIRMATION if confirmation else DUREE_RESERVATION
        expire_le = self.horloge.maintenant + timedelta(seconds=duree)
        return httpx.Response(
            200,
            json={
                "place_id": str(place_id),
                "seance_id": str(seance_id),
                "categorie_id": str(place[1]),
                "commande_id": str(commande_id),
                "expire_le": expire_le.isoformat(),
            },
        )


class FauxPaiements:
    """`POST /api/v1/payments` (creerPaiement) : paiements en mémoire, un par commande.

    `en_panne` : connexion refusée (ConnectError) ; `reponse_forcee` : (statut, code) rendu au
    lieu du paiement (409 SHOW_CANCELLED, 409 PAYMENT_ALREADY_EXISTS).
    """

    def __init__(self, journal: Journal, horloge: Horloge) -> None:
        self.journal = journal
        self.horloge = horloge
        self.paiements: dict[UUID, dict[str, Any]] = {}
        self.en_panne = False
        self.reponse_forcee: tuple[int, str] | None = None

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        appel = self.journal.noter(CIBLE_PAIEMENTS, requete)
        if self.en_panne:
            raise httpx.ConnectError("Paiements injoignable (test)", request=requete)
        if requete.method != "POST" or requete.url.path != "/api/v1/payments" or not appel.corps:
            return _probleme(404, "RESSOURCE_INTROUVABLE")
        if self.reponse_forcee is not None:
            return _probleme(*self.reponse_forcee)
        commande_id = UUID(appel.corps["commande_id"])
        enregistre = self.paiements.setdefault(
            commande_id,
            {
                "id": str(uuid4()),
                "commande_id": str(commande_id),
                "seance_id": appel.corps["seance_id"],
                "montant": appel.corps["montant"],
                "statut": "REFUSE" if appel.corps["carte_test"] == CARTE_REFUSEE else "ACCEPTE",
                "cree_le": self.horloge.maintenant.isoformat(),
            },
        )
        if enregistre["statut"] == "REFUSE":
            return _probleme(402, "PAYMENT_REFUSED")
        return httpx.Response(201, json=enregistre)


# --- Dépôt en mémoire ---------------------------------------------------------------------------


class DepotEnMemoire:
    """Double du port `DepotCommandes`.

    `transaction()` : les écritures et les événements du bloc sont annulés s'il lève ; les
    événements publiés hors transaction sont gardés tout de suite. `semer` pose une commande
    sans passer par le domaine.
    """

    def __init__(self) -> None:
        self.commandes: dict[UUID, Commande] = {}
        self.evenements: list[Evenement] = []
        self.cles_tenues: set[tuple[str, str]] = set()
        self._en_cours: list[Evenement] | None = None

    # --- inspection et données ------------------------------------------------------------------

    def semer(
        self,
        client: str,
        seance_id: UUID,
        statut: StatutCommande,
        lignes: int = 1,
        *,
        email: str | None = None,
        cle: str | None = None,
        cree_le: datetime = MAINTENANT,
        montant: int = 4500,
        place_ids: list[UUID] | None = None,
    ) -> Commande:
        places = place_ids or [uuid4() for _ in range(lignes)]
        commande = Commande(
            id=uuid4(),
            client=client,
            email=email,
            cle_idempotence=cle,
            seance_id=seance_id,
            statut=statut,
            lignes=tuple(LigneCommande(place_id=p, montant=montant) for p in places),
            montant_total=montant * len(places),
            cree_le=cree_le,
            expire_le=cree_le + timedelta(seconds=DUREE_RESERVATION),
        )
        self.commandes[commande.id] = commande
        return commande

    def commandes_de(self, client: str) -> list[Commande]:
        return [c for c in self.commandes.values() if c.client == client]

    def evenements_de(self, type_evenement: str) -> list[Evenement]:
        return [e for e in self.evenements if e.type == type_evenement]

    # --- DepotCommandes -------------------------------------------------------------------------

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        instantane = dict(self.commandes)
        self._en_cours = []
        try:
            yield
        except BaseException:
            self.commandes = instantane
            raise
        else:
            self.evenements.extend(self._en_cours)
        finally:
            self._en_cours = None

    def transaction(self) -> Any:
        return self._transaction()

    async def reserver_cle(self, client: str, cle: str) -> bool:
        if (client, cle) in self.cles_tenues:
            return False
        self.cles_tenues.add((client, cle))
        return True

    async def liberer_cle(self, client: str, cle: str) -> None:
        self.cles_tenues.discard((client, cle))

    async def verrouiller_plafond(self, client: str, seance_id: UUID) -> None:
        return None

    async def compter_billets(self, client: str, seance_id: UUID) -> int:
        comptes = {StatutCommande.EN_ATTENTE, StatutCommande.CONFIRMEE}
        return sum(
            len(c.lignes)
            for c in self.commandes.values()
            if c.client == client and c.seance_id == seance_id and c.statut in comptes
        )

    async def lire_commande(self, client: str, commande_id: UUID) -> Commande | None:
        commande = self.commandes.get(commande_id)
        return commande if commande is not None and commande.client == client else None

    async def lire_par_cle(self, client: str, cle: str) -> Commande | None:
        return next(
            (c for c in self.commandes.values() if c.client == client and c.cle_idempotence == cle),
            None,
        )

    async def lister_commandes(self, client: str, page: int, size: int) -> PageResultat[Commande]:
        ordonnees = sorted(
            self.commandes_de(client), key=lambda c: (-c.cree_le.timestamp(), str(c.id))
        )
        debut = (page - 1) * size
        return PageResultat(elements=ordonnees[debut : debut + size], total=len(ordonnees))

    async def lister_a_expirer(self, maintenant: datetime, limite: int) -> list[Commande]:
        # Tous clients confondus ; sans échéance (expire_le NULL) : jamais lue (décision Q4).
        depassees = [
            c
            for c in self.commandes.values()
            if c.statut is StatutCommande.EN_ATTENTE
            and c.expire_le is not None
            and c.expire_le <= maintenant
        ]
        return sorted(depassees, key=lambda c: (c.expire_le or maintenant, str(c.id)))[:limite]

    async def ajouter_commande(self, commande: Commande) -> None:
        self.commandes[commande.id] = commande

    async def fixer_montants(
        self,
        commande_id: UUID,
        montants: dict[UUID, int],
        montant_total: int,
        expire_le: datetime,
    ) -> None:
        commande = self.commandes[commande_id]
        lignes = tuple(
            replace(ligne, montant=montants.get(ligne.place_id, ligne.montant))
            for ligne in commande.lignes
        )
        self.commandes[commande_id] = replace(
            commande, lignes=lignes, montant_total=montant_total, expire_le=expire_le
        )

    async def changer_statut(
        self, commande_id: UUID, statut: StatutCommande, expire_le: datetime | None = None
    ) -> None:
        commande = self.commandes[commande_id]
        self.commandes[commande_id] = replace(
            commande, statut=statut, expire_le=expire_le or commande.expire_le
        )

    async def publier(self, evenement: Evenement) -> None:
        if self._en_cours is not None:
            self._en_cours.append(evenement)
        else:
            self.evenements.append(evenement)

    # --- annulation.DepotAnnulation (BIL-011) ---------------------------------------------------

    async def commandes_en_attente_de_la_seance(self, seance_id: UUID) -> list[Commande]:
        # `expire_le` NULL compris (Q5) ; tous clients confondus.
        return [
            c
            for c in self.commandes.values()
            if c.seance_id == seance_id and c.statut is StatutCommande.EN_ATTENTE
        ]

    async def lire_commande_verrouillee(self, commande_id: UUID) -> Commande | None:
        return self.commandes.get(commande_id)


# --- Séance commune -----------------------------------------------------------------------------


@dataclass
class Seance:
    """Séance `S` du plan : Fosse 4500 centimes (A1 à A10), Balcon 3000 centimes (C1 à C5)."""

    id: UUID
    fosse: UUID
    balcon: UUID
    places: dict[str, UUID] = field(default_factory=dict)

    def __getitem__(self, nom: str) -> UUID:
        return self.places[nom]

    def corps(self, *noms: str, carte: str = "4242424242424242") -> dict[str, Any]:
        """Corps `CommandeCreation` pour les places nommées."""
        return {
            "seance_id": str(self.id),
            "place_ids": [str(self.places[n]) for n in noms],
            "carte_test": carte,
        }


def seance_catalogue(
    seance_id: UUID, fosse: UUID, balcon: UUID, debut: datetime, annulee: bool = False
) -> dict[str, Any]:
    """Corps `Seance` de lireSeanceParId (contrat docs/contrats/catalogue.yaml)."""
    return {
        "id": str(seance_id),
        "evenement_id": str(uuid4()),
        "lieu_id": str(uuid4()),
        "debut": debut.isoformat(),
        "annulee": annulee,
        "categories": [
            {
                "id": str(fosse),
                "nom": "Fosse",
                "prix": 4500,
                "rangs": [{"rang": "A", "nombre_places": 10}],
            },
            {
                "id": str(balcon),
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
def journal() -> Journal:
    return Journal()


@pytest.fixture
def depot() -> DepotEnMemoire:
    return DepotEnMemoire()


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


@pytest.fixture
def keycloak(emetteur: EmetteurDeTest) -> FauxKeycloak:
    return FauxKeycloak(emetteur)


@pytest.fixture
def catalogue(journal: Journal) -> FauxCatalogue:
    return FauxCatalogue(journal)


@pytest.fixture
def billets(journal: Journal, horloge: Horloge) -> FauxBillets:
    return FauxBillets(journal, horloge)


@pytest.fixture
def paiements(journal: Journal, horloge: Horloge) -> FauxPaiements:
    return FauxPaiements(journal, horloge)


@pytest.fixture
def seance(catalogue: FauxCatalogue, billets: FauxBillets, horloge: Horloge) -> Seance:
    """`S` : `debut` = maintenant + 30 j, non annulée, connue de Catalogue et de Billets."""
    seance = Seance(id=uuid4(), fosse=uuid4(), balcon=uuid4())
    for rang, nombre, categorie in (("A", 10, seance.fosse), ("C", 5, seance.balcon)):
        for numero in range(1, nombre + 1):
            place_id = uuid4()
            seance.places[f"{rang}{numero}"] = place_id
            billets.places[place_id] = (seance.id, categorie)
    catalogue.seances[seance.id] = seance_catalogue(
        seance.id, seance.fosse, seance.balcon, horloge.maintenant + timedelta(days=30)
    )
    return seance


async def _pas_d_attente(_secondes: float) -> None:
    return None


@pytest.fixture
async def clients_http(
    keycloak: FauxKeycloak,
    catalogue: FauxCatalogue,
    billets: FauxBillets,
    paiements: FauxPaiements,
) -> AsyncIterator[tuple[ClientCatalogue, ClientBillets, ClientPaiements]]:
    """Vrais clients de Commandes sur `ClientService` + `MockTransport`, jeton de service réel."""
    jeton = JetonService(
        URL_JETON,
        "services",
        secrets.token_urlsafe(16),
        transport=httpx.MockTransport(keycloak),
    )

    def service(cible: str, faux: Callable[[httpx.Request], httpx.Response]) -> ClientService:
        return ClientService(
            cible,
            URL_GATEWAY,
            jeton=jeton,
            transport=httpx.MockTransport(faux),
            attente=_pas_d_attente,
            disjoncteur_cible=Disjoncteur(cible),
        )

    services = [
        service(CIBLE_CATALOGUE, catalogue),
        service(CIBLE_BILLETS, billets),
        service(CIBLE_PAIEMENTS, paiements),
    ]
    try:
        yield (
            ClientCatalogueHttp(services[0]),
            ClientBilletsHttp(services[1]),
            ClientPaiementsHttp(services[2]),
        )
    finally:
        for client in services:
            await client.aclose()
        await jeton.aclose()


FabriqueApp = Callable[..., FastAPI]


@pytest.fixture
def fabrique_app(
    emetteur: EmetteurDeTest,
    depot: DepotEnMemoire,
    horloge: Horloge,
    clients_http: tuple[ClientCatalogue, ClientBillets, ClientPaiements],
) -> FabriqueApp:
    """Application sur les doubles ; les arguments nommés vont à `Parametres`."""

    def fabriquer(**reglages: Any) -> FastAPI:
        reglages.setdefault("database_url", URL_BASE)
        reglages.setdefault("redis_url", URL_REDIS)
        config = Parametres(
            instance="commandes-test", consul_actif=False, url_gateway=URL_GATEWAY, **reglages
        )
        application = creer_app(config, verificateur_jetons=emetteur.verificateur())
        catalogue_http, billets_http, paiements_http = clients_http

        def depot_de_test() -> DepotCommandes:
            return depot

        def catalogue_de_test() -> ClientCatalogue:
            return catalogue_http

        def billets_de_test() -> ClientBillets:
            return billets_http

        def paiements_de_test() -> ClientPaiements:
            return paiements_http

        application.dependency_overrides[obtenir_depot] = depot_de_test
        application.dependency_overrides[obtenir_catalogue] = catalogue_de_test
        application.dependency_overrides[obtenir_billets] = billets_de_test
        application.dependency_overrides[obtenir_paiements] = paiements_de_test
        application.dependency_overrides[obtenir_maintenant] = lambda: horloge.maintenant
        return application

    return fabriquer


@pytest.fixture
def app(fabrique_app: FabriqueApp) -> FastAPI:
    return fabrique_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Client sans jeton par défaut ; une erreur imprévue sort en 500 (pas d'exception)."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# --- Appelants du plan --------------------------------------------------------------------------


@pytest.fixture
def entetes_a(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(
        sujet="client-a",
        roles=["customer"],
        scopes=SCOPES_COMMANDES,
        email="client.test@exemple.test",
    )


@pytest.fixture
def entetes_b(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(
        sujet="client-b",
        roles=["customer"],
        scopes=SCOPES_COMMANDES,
        email="client.b.test@exemple.test",
    )


@pytest.fixture
def entetes_r1(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(
        sujet="sujet-revendeur-test",
        roles=["partner"],
        scopes=SCOPES_COMMANDES,
        client="revendeur-test",
    )


@pytest.fixture
def entetes_r2(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(
        sujet="sujet-revendeur-test-2",
        roles=["partner"],
        scopes=SCOPES_COMMANDES,
        client="revendeur-test-2",
    )


@pytest.fixture
def entetes_admin(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(roles=["admin"], scopes=["events:read", "events:write"])


@pytest.fixture
def environnement_propre(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for variable in (
        "LIMITE_BILLETS_PAR_SEANCE",
        "URL_GATEWAY",
        "URL_JETON",
        "REDIS_URL",
        "EXPIRATION_PERIODE",
        "EXPIRATION_LOT",
    ):
        monkeypatch.delenv(variable, raising=False)
    yield
