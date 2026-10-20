"""API Gateway Traefik : répartition, retrait, limitation de débit, corrélation et CORS.

Traefik tourne avec la configuration réelle de infra/traefik/ ; les routes viennent
uniquement des tags Consul posés par commun.registre.
"""

import re
import time
from collections import Counter

import anyio
import httpx
import pytest

from commun.registre import desenregistrer, enregistrer, tags_traefik

pytestmark = pytest.mark.anyio

PORT_WHOAMI = 80


@pytest.fixture(autouse=True)
def variable_consul(consul_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSUL_URL", consul_url)


def _nom_instance(reponse: httpx.Response) -> str:
    trouve = re.search(r"^Name: (.+)$", reponse.text, re.MULTILINE)
    assert trouve, reponse.text
    return trouve.group(1).strip()


def _route(service: str) -> str:
    # Une route par test : Traefik garde l'ancien routeur quelques secondes après un
    # désenregistrement, une route partagée mélangerait les tests.
    return f"/api/v1/{service}"


async def _inscrire(noms: list[str], service: str, middlewares: str) -> list[str]:
    tags = tags_traefik(service, service, middlewares=middlewares)
    return [await enregistrer(service, nom, PORT_WHOAMI, tags) for nom in noms]


async def _attendre_instances(
    client: httpx.AsyncClient, route: str, attendues: set[str], delai: float = 45.0
) -> None:
    """Attend que Traefik route exactement vers les instances attendues."""
    limite = time.monotonic() + delai
    vues: set[str] = set()
    while time.monotonic() < limite:
        vues = set()
        for _ in range(10):
            reponse = await client.get(route)
            if reponse.status_code == 200:
                vues.add(_nom_instance(reponse))
        if vues == attendues:
            return
        await anyio.sleep(1)
    raise AssertionError(f"Instances routées : {vues}, attendues : {attendues}")


async def test_deux_instances_se_partagent_les_appels_puis_une_instance_retiree_n_en_recoit_plus(
    gateway_url: str, instances_whoami: list[str]
) -> None:
    identifiants = await _inscrire(instances_whoami, "repartition", "standard@file")
    route = _route("repartition")
    async with httpx.AsyncClient(base_url=gateway_url) as client:
        await _attendre_instances(client, route, set(instances_whoami))

        # CA1 : chaque instance reçoit une part des appels.
        repartition = Counter([_nom_instance(await client.get(route)) for _ in range(20)])
        assert set(repartition) == set(instances_whoami)
        assert min(repartition.values()) >= 5, repartition

        # CA2 : une instance retirée de Consul ne reçoit plus d'appel.
        await desenregistrer(identifiants[1])
        await _attendre_instances(client, route, {instances_whoami[0]})
        noms = {_nom_instance(await client.get(route)) for _ in range(20)}
        assert noms == {instances_whoami[0]}

    await desenregistrer(identifiants[0])


async def test_correlation_creee_si_absente_et_conservee_si_fournie(
    gateway_url: str, instances_whoami: list[str]
) -> None:
    identifiants = await _inscrire(instances_whoami, "correlation", "standard@file")
    route = _route("correlation")
    async with httpx.AsyncClient(base_url=gateway_url) as client:
        await _attendre_instances(client, route, set(instances_whoami))

        reponse = await client.get(route)
        cree = reponse.headers["X-Correlation-Id"]
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", cree
        )
        assert f"X-Correlation-Id: {cree}" in reponse.text  # transmis au service

        fourni = "identifiant-du-client"
        reponse = await client.get(route, headers={"X-Correlation-Id": fourni})
        assert reponse.headers["X-Correlation-Id"] == fourni
        assert f"X-Correlation-Id: {fourni}" in reponse.text

    for identifiant in identifiants:
        await desenregistrer(identifiant)


async def test_cors_autorise_seulement_les_origines_configurees(
    gateway_url: str, instances_whoami: list[str], origine_front: str
) -> None:
    identifiants = await _inscrire(instances_whoami, "cors", "standard@file")
    route = _route("cors")
    async with httpx.AsyncClient(base_url=gateway_url) as client:
        await _attendre_instances(client, route, set(instances_whoami))

        def preflight(origine: str) -> dict[str, str]:
            return {"Origin": origine, "Access-Control-Request-Method": "POST"}

        autorisee = await client.options(route, headers=preflight(origine_front))
        assert autorisee.headers.get("Access-Control-Allow-Origin") == origine_front

        refusee = await client.options(route, headers=preflight("https://pirate.exemple"))
        assert "Access-Control-Allow-Origin" not in refusee.headers

    for identifiant in identifiants:
        await desenregistrer(identifiant)


async def test_au_dela_de_la_limite_partenaire_la_gateway_repond_429(
    gateway_url: str, instances_whoami: list[str]
) -> None:
    identifiants = await _inscrire(instances_whoami, "partenaires", "partenaires@file")
    route = _route("partenaires")
    async with httpx.AsyncClient(base_url=gateway_url) as client:
        await _attendre_instances(client, route, set(instances_whoami))
        # Laisse le seau du limiteur se remplir après les appels d'attente.
        await anyio.sleep(3)

        jeton = {"Authorization": "Bearer revendeur-a"}
        codes = [(await client.get(route, headers=jeton)).status_code for _ in range(30)]
        assert 200 in codes
        assert 429 in codes, codes

        # Le quota est compté par jeton : un autre revendeur n'est pas bloqué.
        autre = await client.get(route, headers={"Authorization": "Bearer revendeur-b"})
        assert autre.status_code == 200

    for identifiant in identifiants:
        await desenregistrer(identifiant)


async def test_au_dela_de_la_limite_generale_la_gateway_repond_429(
    gateway_url: str, instances_whoami: list[str]
) -> None:
    identifiants = await _inscrire(instances_whoami, "general", "standard@file")
    route = _route("general")
    # Sans plafond de connexions : le client doit envoyer plus vite que le remplissage du
    # seau (50 appels par seconde), sinon la limite n'est jamais atteinte.
    sans_plafond = httpx.Limits(max_connections=None, max_keepalive_connections=None)
    async with httpx.AsyncClient(base_url=gateway_url, limits=sans_plafond) as client:
        await _attendre_instances(client, route, set(instances_whoami))
        await anyio.sleep(3)

        codes: list[int] = []

        async def appel() -> None:
            codes.append((await client.get(route)).status_code)

        # Vagues de 200 appels simultanés jusqu'au premier 429 (rafale autorisée : 100).
        for _ in range(5):
            async with anyio.create_task_group() as groupe:
                for _ in range(200):
                    groupe.start_soon(appel)
            if 429 in codes:
                break

        assert 429 in codes, Counter(codes)

    for identifiant in identifiants:
        await desenregistrer(identifiant)
