"""Liste paginée des echos (GET /api/v1/echos, scope echos:read), sans base ni Keycloak."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from commun.faux_jetons import EmetteurDeTest
from echo.api.dependances import obtenir_depot
from echo.api.schemas import EchoPage
from echo.config import Parametres
from echo.domaine.echos import DepotEchos, Echo, EchoDejaExistant
from echo.principal import creer_app

pytestmark = pytest.mark.anyio

INSTANCE = "echo-test"
ROUTE = "/api/v1/echos"
ORIGINE = datetime(2026, 10, 20, tzinfo=UTC)


class DepotEnMemoire:
    """Dépôt en mémoire ; `semer` pose un echo avec une date `cree_le` choisie par le test."""

    def __init__(self) -> None:
        self.echos: dict[str, Echo] = {}

    def semer(self, message: str, cree_le: datetime) -> None:
        self.echos[message] = Echo(message=message, cree_le=cree_le)

    async def ajouter(self, message: str) -> Echo:
        if message in self.echos:
            raise EchoDejaExistant(message)
        self.echos[message] = Echo(message=message, cree_le=ORIGINE)
        return self.echos[message]

    async def trouver(self, message: str) -> Echo | None:
        return self.echos.get(message)

    async def lister(self, decalage: int, limite: int) -> list[Echo]:
        # Ordre total : cree_le décroissant, puis message croissant (validation 1, Q2).
        par_message = sorted(self.echos.values(), key=lambda echo: echo.message)
        ordonnes = sorted(par_message, key=lambda echo: echo.cree_le, reverse=True)
        return ordonnes[decalage : decalage + limite]

    async def compter(self) -> int:
        return len(self.echos)


def _semer_numerotes(depot: DepotEnMemoire, nombre: int) -> None:
    """`message-test-01` à `message-test-<nombre>`, chacun une minute après le précédent."""
    for rang in range(1, nombre + 1):
        depot.semer(f"message-test-{rang:02d}", ORIGINE + timedelta(minutes=rang))


def _messages(corps: dict[str, Any]) -> list[str]:
    return [element["message"] for element in corps["elements"]]


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


@pytest.fixture
def depot() -> DepotEnMemoire:
    return DepotEnMemoire()


@pytest.fixture
async def anonyme(
    emetteur: EmetteurDeTest, depot: DepotEnMemoire
) -> AsyncIterator[httpx.AsyncClient]:
    """Client sans jeton ; chaque test choisit l'appelant qu'il simule."""
    config = Parametres(database_url="postgresql+asyncpg://test@localhost/echo", instance=INSTANCE)
    app = creer_app(config, verificateur_jetons=emetteur.verificateur())

    def depot_de_test() -> DepotEchos:
        return depot

    app.dependency_overrides[obtenir_depot] = depot_de_test
    # Sans lifespan : ni base ni Consul ne sont démarrés.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def lecteur(anonyme: httpx.AsyncClient, emetteur: EmetteurDeTest) -> httpx.AsyncClient:
    """Compte de service autorisé à lire la liste (scope echos:read)."""
    anonyme.headers.update(emetteur.entetes(client="services", scopes=["echos:read"]))
    return anonyme


# D1 : le scope echos:read


async def test_lister_les_echos_avec_le_scope_echos_read_renvoie_200(
    lecteur: httpx.AsyncClient, depot: DepotEnMemoire
) -> None:
    _semer_numerotes(depot, 2)

    reponse = await lecteur.get(ROUTE)

    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "application/json"
    EchoPage.model_validate(reponse.json())


async def test_sans_jeton_la_liste_repond_401(anonyme: httpx.AsyncClient) -> None:
    reponse = await anonyme.get(ROUTE)

    assert reponse.status_code == 401
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.headers["WWW-Authenticate"].startswith("Bearer")
    assert reponse.json()["code"] == "JETON_ABSENT"


async def test_un_jeton_expire_sur_la_liste_recoit_401(
    anonyme: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    reponse = await anonyme.get(
        ROUTE, headers=emetteur.entetes(scopes=["echos:read"], expire_dans=-3600)
    )

    assert reponse.status_code == 401
    assert reponse.json()["code"] == "JETON_EXPIRE"


async def test_un_jeton_avec_seulement_echos_write_recoit_403_sur_la_liste(
    anonyme: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    reponse = await anonyme.get(
        ROUTE, headers=emetteur.entetes(client="services", scopes=["echos:write"])
    )

    assert reponse.status_code == 403
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme = reponse.json()
    assert probleme["code"] == "SCOPE_MANQUANT"
    assert probleme["detail"] == "Scope requis : echos:read."


async def test_un_client_sans_scope_echos_recoit_403_sur_la_liste(
    anonyme: httpx.AsyncClient, emetteur: EmetteurDeTest
) -> None:
    reponse = await anonyme.get(
        ROUTE, headers=emetteur.entetes(roles=["customer"], scopes=["openid", "profile"])
    )

    assert reponse.status_code == 403
    assert reponse.json()["code"] == "SCOPE_MANQUANT"


# D2 : réponse paginée {elements, page, size, total}


def test_echo_page_garde_le_nom_du_contrat() -> None:
    schema = EchoPage.model_json_schema()

    assert schema["title"] == "EchoPage"
    assert schema["properties"]["elements"]["items"] == {"$ref": "#/$defs/EchoReponse"}
    assert set(schema["required"]) == {"elements", "page", "size", "total"}


async def test_le_total_compte_tous_les_echos_et_non_ceux_de_la_page(
    lecteur: httpx.AsyncClient, depot: DepotEnMemoire
) -> None:
    _semer_numerotes(depot, 25)

    reponse = await lecteur.get(ROUTE, params={"size": 10})

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps["elements"]) == 10
    assert corps["total"] == 25


# D3 : pagination à partir de 1, page >= 1 (1 par défaut), size de 1 à 100 (20 par défaut)


async def test_sans_parametres_la_liste_renvoie_la_page_1_de_20_elements(
    lecteur: httpx.AsyncClient, depot: DepotEnMemoire
) -> None:
    _semer_numerotes(depot, 25)

    reponse = await lecteur.get(ROUTE)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["page"] == 1
    assert corps["size"] == 20
    assert len(corps["elements"]) == 20
    assert corps["total"] == 25


async def test_la_derniere_page_contient_le_reste_des_echos(
    lecteur: httpx.AsyncClient, depot: DepotEnMemoire
) -> None:
    _semer_numerotes(depot, 25)

    reponse = await lecteur.get(ROUTE, params={"page": 2, "size": 20})

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["page"] == 2
    assert _messages(corps) == [
        "message-test-05",
        "message-test-04",
        "message-test-03",
        "message-test-02",
        "message-test-01",
    ]


@pytest.mark.parametrize(
    ("parametres", "nombre_attendu", "size_attendu"),
    [({"page": 1, "size": 1}, 1, 1), ({"size": 100}, 3, 100)],
)
async def test_les_bornes_de_pagination_sont_acceptees(
    lecteur: httpx.AsyncClient,
    depot: DepotEnMemoire,
    parametres: dict[str, int],
    nombre_attendu: int,
    size_attendu: int,
) -> None:
    _semer_numerotes(depot, 3)

    reponse = await lecteur.get(ROUTE, params=parametres)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps["elements"]) == nombre_attendu
    assert corps["size"] == size_attendu


@pytest.mark.parametrize(
    "parametres",
    [
        {"page": "0"},
        {"page": "-1"},
        {"size": "0"},
        {"size": "101"},
        {"page": "abc"},
        {"size": "abc"},
    ],
)
async def test_des_parametres_de_pagination_invalides_renvoient_422_problem_details(
    lecteur: httpx.AsyncClient, parametres: dict[str, str]
) -> None:
    reponse = await lecteur.get(ROUTE, params=parametres)

    assert reponse.status_code == 422
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme = reponse.json()
    assert probleme["code"] == "REQUETE_INVALIDE"
    assert probleme["erreurs"][0]["champ"].startswith("query")


# D4 : éléments au format EchoReponse


async def test_chaque_element_porte_message_instance_et_cree_le(
    lecteur: httpx.AsyncClient, depot: DepotEnMemoire
) -> None:
    depot.semer("message-test-01", datetime(2026, 10, 20, tzinfo=UTC))

    reponse = await lecteur.get(ROUTE)

    assert reponse.status_code == 200
    assert reponse.json()["elements"] == [
        {"message": "message-test-01", "instance": INSTANCE, "cree_le": "2026-10-20T00:00:00Z"}
    ]


# D5 : tri par cree_le décroissant, sans paramètre de tri ni filtre


async def test_les_echos_sont_listes_du_plus_recent_au_plus_ancien(
    lecteur: httpx.AsyncClient, depot: DepotEnMemoire
) -> None:
    depot.semer("message-test-20", datetime(2026, 10, 20, tzinfo=UTC))
    depot.semer("message-test-22", datetime(2026, 10, 22, tzinfo=UTC))
    depot.semer("message-test-21", datetime(2026, 10, 21, tzinfo=UTC))

    reponse = await lecteur.get(ROUTE)

    assert reponse.status_code == 200
    assert _messages(reponse.json()) == ["message-test-22", "message-test-21", "message-test-20"]


@pytest.mark.parametrize("parametres", [{"tri": "message"}, {"message": "message-test-01"}])
async def test_un_parametre_de_tri_ou_de_filtre_inconnu_est_ignore(
    lecteur: httpx.AsyncClient, depot: DepotEnMemoire, parametres: dict[str, str]
) -> None:
    _semer_numerotes(depot, 3)

    reponse = await lecteur.get(ROUTE, params=parametres)

    assert reponse.status_code == 200
    assert _messages(reponse.json()) == ["message-test-03", "message-test-02", "message-test-01"]


# D6 : page au-delà de la fin


async def test_une_page_au_dela_de_la_fin_renvoie_200_et_une_liste_vide(
    lecteur: httpx.AsyncClient, depot: DepotEnMemoire
) -> None:
    _semer_numerotes(depot, 3)

    reponse = await lecteur.get(ROUTE, params={"page": 5})

    assert reponse.status_code == 200
    assert reponse.json() == {"elements": [], "page": 5, "size": 20, "total": 3}


async def test_sans_aucun_echo_la_liste_renvoie_une_page_vide(lecteur: httpx.AsyncClient) -> None:
    reponse = await lecteur.get(ROUTE)

    assert reponse.status_code == 200
    assert reponse.json() == {"elements": [], "page": 1, "size": 20, "total": 0}
