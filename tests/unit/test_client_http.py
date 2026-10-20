"""Client HTTP entre services (commun.http) avec un faux transport : aucun réseau."""

from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY

from commun.correlation import MiddlewareCorrelation
from commun.erreurs import installer_erreurs
from commun.http import (
    ClientService,
    Disjoncteur,
    Etat,
    JetonService,
    ServiceIndisponible,
    disjoncteur,
)

pytestmark = pytest.mark.anyio


class Horloge:
    def __init__(self) -> None:
        self.maintenant = 1000.0

    def __call__(self) -> float:
        return self.maintenant

    def avancer(self, secondes: float) -> None:
        self.maintenant += secondes


class FausseCible:
    """Répond avec les statuts programmés et garde chaque requête reçue."""

    def __init__(self, *reponses: int | type[Exception]) -> None:
        self.reponses = list(reponses)
        self.requetes: list[httpx.Request] = []

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.requetes.append(requete)
        reponse = self.reponses.pop(0) if len(self.reponses) > 1 else self.reponses[0]
        if isinstance(reponse, int):
            return httpx.Response(reponse, json={"statut": reponse})
        raise reponse("panne simulée", request=requete)  # type: ignore[call-arg]


async def sans_attente(_secondes: float) -> None:
    """Remplace asyncio.sleep : les tests ne patientent pas pendant le backoff."""


@pytest.fixture
def horloge() -> Horloge:
    return Horloge()


@pytest.fixture
def fabrique(horloge: Horloge) -> Callable[..., ClientService]:
    def creer(cible: FausseCible, **options: object) -> ClientService:
        return ClientService(
            "catalogue",
            "http://gateway",
            transport=httpx.MockTransport(cible),
            attente=sans_attente,
            disjoncteur_cible=Disjoncteur("catalogue", horloge=horloge),
            **options,  # type: ignore[arg-type]
        )

    return creer


async def test_un_get_en_echec_est_rejoue_trois_fois_au_maximum(
    fabrique: Callable[..., ClientService],
) -> None:
    cible = FausseCible(503, 502, 200)
    async with fabrique(cible) as client:
        reponse = await client.get("/api/v1/seances")

    assert reponse.status_code == 200
    assert len(cible.requetes) == 3


async def test_les_tentatives_sont_espacees_d_une_attente_aleatoire_bornee(
    horloge: Horloge,
) -> None:
    attentes: list[float] = []

    async def noter(secondes: float) -> None:
        attentes.append(secondes)

    cible = FausseCible(503)
    async with ClientService(
        "salles",
        "http://gateway",
        transport=httpx.MockTransport(cible),
        attente=noter,
        disjoncteur_cible=Disjoncteur("salles", horloge=horloge),
    ) as client:
        for _ in range(20):
            with pytest.raises(ServiceIndisponible):
                await client.get("/api/v1/salles")
            client._disjoncteur.succes()  # garde le disjoncteur fermé pour ce test

    # Deux attentes par appel (entre les 3 tentatives), jamais au-delà du plafond d'1 s.
    assert len(attentes) == 40
    assert all(0 <= attente <= 1.0 for attente in attentes)
    assert len(set(attentes)) > 1  # gigue : les attentes ne sont pas toutes identiques


async def test_apres_trois_tentatives_le_get_leve_service_indisponible(
    fabrique: Callable[..., ClientService],
) -> None:
    cible = FausseCible(httpx.ConnectError)
    async with fabrique(cible) as client:
        with pytest.raises(ServiceIndisponible) as erreur:
            await client.get("/api/v1/seances")

    assert len(cible.requetes) == 3
    assert erreur.value.statut == 503
    assert erreur.value.code == "SERVICE_INDISPONIBLE"


@pytest.mark.parametrize("panne", [503, httpx.ReadTimeout, httpx.ConnectError])
async def test_un_post_sans_cle_d_idempotence_n_est_jamais_rejoue(
    fabrique: Callable[..., ClientService], panne: int | type[Exception]
) -> None:
    cible = FausseCible(panne, 201)
    async with fabrique(cible) as client:
        with pytest.raises(ServiceIndisponible):
            await client.post("/api/v1/commandes", json={"places": 2})

    assert len(cible.requetes) == 1  # CA1


async def test_un_post_avec_cle_d_idempotence_est_rejoue_avec_la_meme_cle(
    fabrique: Callable[..., ClientService],
) -> None:
    cible = FausseCible(503, 201)
    async with fabrique(cible) as client:
        reponse = await client.post("/api/v1/commandes", json={}, cle_idempotence="cmd-42")

    assert reponse.status_code == 201
    assert [r.headers["Idempotency-Key"] for r in cible.requetes] == ["cmd-42", "cmd-42"]


async def test_une_erreur_4xx_est_rendue_sans_rejeu_ni_echec(
    fabrique: Callable[..., ClientService], horloge: Horloge
) -> None:
    cible = FausseCible(404)
    async with fabrique(cible) as client:
        for _ in range(10):
            assert (await client.get("/api/v1/seances/inconnue")).status_code == 404

    assert len(cible.requetes) == 10
    assert client._disjoncteur.etat is Etat.FERME


async def test_apres_5_echecs_les_appels_echouent_sans_reseau(
    fabrique: Callable[..., ClientService],
) -> None:
    cible = FausseCible(503)
    async with fabrique(cible, tentatives_max=1) as client:
        for _ in range(5):
            with pytest.raises(ServiceIndisponible):
                await client.get("/api/v1/seances")
        assert client._disjoncteur.etat is Etat.OUVERT

        # CA2 : la cible n'est plus appelée du tout.
        for _ in range(20):
            with pytest.raises(ServiceIndisponible):
                await client.get("/api/v1/seances")

    assert len(cible.requetes) == 5


async def test_chaque_tentative_compte_comme_un_echec(
    fabrique: Callable[..., ClientService],
) -> None:
    cible = FausseCible(503)
    async with fabrique(cible) as client:
        for _ in range(2):
            with pytest.raises(ServiceIndisponible):
                await client.get("/api/v1/seances")

    # 2 appels : 3 tentatives puis 2 (le disjoncteur s'ouvre à la cinquième).
    assert len(cible.requetes) == 5
    assert client._disjoncteur.etat is Etat.OUVERT


async def test_le_disjoncteur_se_referme_apres_un_essai_reussi(
    fabrique: Callable[..., ClientService], horloge: Horloge
) -> None:
    cible = FausseCible(503, 503, 503, 503, 503, 200)
    async with fabrique(cible, tentatives_max=1) as client:
        for _ in range(5):
            with pytest.raises(ServiceIndisponible):
                await client.get("/api/v1/seances")

        horloge.avancer(29)
        with pytest.raises(ServiceIndisponible):
            await client.get("/api/v1/seances")  # encore ouvert, sans réseau
        horloge.avancer(1)
        assert client._disjoncteur.etat is Etat.DEMI_OUVERT

        # CA3 : l'appel d'essai réussit, le disjoncteur se referme.
        assert (await client.get("/api/v1/seances")).status_code == 200
        assert client._disjoncteur.etat is Etat.FERME
        assert (await client.get("/api/v1/seances")).status_code == 200

    assert len(cible.requetes) == 7


async def test_un_essai_rate_en_demi_ouvert_rouvre_pour_30_secondes(
    fabrique: Callable[..., ClientService], horloge: Horloge
) -> None:
    cible = FausseCible(503)
    async with fabrique(cible, tentatives_max=1) as client:
        for _ in range(5):
            with pytest.raises(ServiceIndisponible):
                await client.get("/api/v1/seances")
        horloge.avancer(30)

        with pytest.raises(ServiceIndisponible):
            await client.get("/api/v1/seances")  # l'essai échoue
        assert client._disjoncteur.etat is Etat.OUVERT
        horloge.avancer(29)
        assert client._disjoncteur.etat is Etat.OUVERT

    assert len(cible.requetes) == 6


def test_en_demi_ouvert_un_seul_essai_passe_a_la_fois(horloge: Horloge) -> None:
    disjoncteur_test = Disjoncteur("billets", seuil=1, horloge=horloge)
    disjoncteur_test.echec()
    horloge.avancer(30)

    assert disjoncteur_test.autoriser() is True
    assert disjoncteur_test.autoriser() is False  # un autre appel pendant l'essai
    disjoncteur_test.abandon()
    assert disjoncteur_test.autoriser() is True


def test_l_etat_du_disjoncteur_est_publie_en_metrique(horloge: Horloge) -> None:
    disjoncteur_test = Disjoncteur("paiements", seuil=1, horloge=horloge)

    def valeur() -> float | None:
        return REGISTRY.get_sample_value("client_http_disjoncteur_etat", {"cible": "paiements"})

    assert valeur() == 0
    disjoncteur_test.echec()
    assert valeur() == 2
    horloge.avancer(30)
    assert disjoncteur_test.etat is Etat.DEMI_OUVERT
    assert valeur() == 1


def test_le_disjoncteur_d_une_cible_est_partage() -> None:
    assert disjoncteur("notifications") is disjoncteur("notifications")
    assert disjoncteur("notifications") is not disjoncteur("billets")


async def test_le_timeout_par_defaut_est_de_2_secondes() -> None:
    async with ClientService("billets", "http://gateway") as client:
        assert client._client.timeout == httpx.Timeout(2.0)


class FauxKeycloak:
    def __init__(self) -> None:
        self.appels = 0

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.appels += 1
        assert b"grant_type=client_credentials" in requete.content
        return httpx.Response(200, json={"access_token": f"jeton-{self.appels}", "expires_in": 300})


async def test_le_jeton_de_service_est_ajoute_et_mis_en_cache_jusqu_a_expiration(
    fabrique: Callable[..., ClientService], horloge: Horloge
) -> None:
    keycloak = FauxKeycloak()
    jeton = JetonService(
        "http://keycloak/token", "services", "secret", httpx.MockTransport(keycloak), horloge
    )
    cible = FausseCible(200)
    async with fabrique(cible, jeton=jeton) as client:
        for _ in range(3):
            await client.get("/api/v1/seances")
        horloge.avancer(300 - 30)  # expiration moins la marge
        await client.get("/api/v1/seances")
    await jeton.aclose()

    autorisations = [r.headers["Authorization"] for r in cible.requetes]
    assert autorisations == ["Bearer jeton-1"] * 3 + ["Bearer jeton-2"]
    assert keycloak.appels == 2


async def test_keycloak_injoignable_donne_service_indisponible() -> None:
    def en_panne(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("panne", request=requete)

    jeton = JetonService("http://keycloak/token", "services", "s", httpx.MockTransport(en_panne))
    with pytest.raises(ServiceIndisponible) as erreur:
        await jeton.jeton()
    await jeton.aclose()

    assert erreur.value.cible == "keycloak"


@pytest.fixture
async def service_appelant(
    fabrique: Callable[..., ClientService],
) -> AsyncIterator[tuple[httpx.AsyncClient, FausseCible]]:
    """Un service FastAPI qui appelle le catalogue avec ClientService."""
    cible = FausseCible(200)
    catalogue = fabrique(cible)
    app = FastAPI()
    installer_erreurs(app)
    app.add_middleware(MiddlewareCorrelation)

    @app.get("/places")
    async def places() -> dict[str, int]:
        reponse = await catalogue.get("/api/v1/seances")
        return {"statut_catalogue": reponse.status_code}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, cible
    await catalogue.aclose()


async def test_l_identifiant_de_correlation_est_propage(
    service_appelant: tuple[httpx.AsyncClient, FausseCible],
) -> None:
    client, cible = service_appelant

    await client.get("/places", headers={"X-Correlation-Id": "requete-7"})

    assert cible.requetes[0].headers["X-Correlation-Id"] == "requete-7"


async def test_service_indisponible_devient_un_problem_details_503(
    service_appelant: tuple[httpx.AsyncClient, FausseCible],
) -> None:
    client, cible = service_appelant
    cible.reponses = [503]

    reponse = await client.get("/places", headers={"X-Correlation-Id": "requete-8"})

    assert reponse.status_code == 503
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json() == {
        "type": "about:blank",
        "title": "Service indisponible",
        "status": 503,
        "detail": "Le service catalogue est momentanément indisponible.",
        "code": "SERVICE_INDISPONIBLE",
        "correlation_id": "requete-8",
    }
