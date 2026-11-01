"""CA3 (BIL-004, décision Q2) : catalogue s'inscrit dans un vrai Consul avec ses trois préfixes.

Consul 1.21.5 en mode dev, base migrée, `creer_app(consul_actif=True)` sous lifespan, instance
`catalogue-test`. Tags attendus : routeur `catalogue` sur `events`, `venues` et `shows`
(entrypoint `web`, chaîne `standard@file`) et routeur `catalogue-sante` sur
`/api/v1/events/health`.
"""

import time
from collections.abc import Iterator
from typing import Any

import anyio
import httpx
import pytest
from testcontainers.core.container import DockerContainer

from catalogue.config import Parametres
from catalogue.principal import creer_app
from commun.faux_jetons import EmetteurDeTest
from commun.registre import PRIORITE_ROUTEUR_SANTE

pytestmark = pytest.mark.anyio

IMAGE_CONSUL = "hashicorp/consul:1.21.5"
INSTANCE = "catalogue-test"
REGLE = (
    "PathPrefix(`/api/v1/events`) || PathPrefix(`/api/v1/venues`) || PathPrefix(`/api/v1/shows`)"
)
TAGS_ATTENDUS = {
    "traefik.enable=true",
    f"traefik.http.routers.catalogue.rule={REGLE}",
    "traefik.http.routers.catalogue.entrypoints=web",
    "traefik.http.routers.catalogue.middlewares=standard@file",
    "traefik.http.routers.catalogue-sante.rule=Path(`/api/v1/events/health`) && Method(`GET`)",
    f"traefik.http.routers.catalogue-sante.priority={PRIORITE_ROUTEUR_SANTE}",
    "traefik.http.routers.catalogue-sante.entrypoints=web",
    "traefik.http.routers.catalogue-sante.middlewares=standard@file,catalogue-sante",
    "traefik.http.middlewares.catalogue-sante.replacepath.path=/health",
}
DELAI_PREMIER_CHECK = 60.0


@pytest.fixture(scope="module")
def consul_url() -> Iterator[str]:
    consul = (
        DockerContainer(IMAGE_CONSUL)
        .with_command("agent -dev -client=0.0.0.0")
        .with_exposed_ports(8500)
    )
    with consul:
        hote = consul.get_container_host_ip().replace("localhost", "127.0.0.1")
        url = f"http://{hote}:{consul.get_exposed_port(8500)}"
        limite = time.monotonic() + 60
        while time.monotonic() < limite:
            try:
                if httpx.get(f"{url}/v1/status/leader", timeout=2.0).json():
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise AssertionError("Consul n'a pas élu de leader en 60 s")
        yield url


async def _check_execute(consul: httpx.AsyncClient, service_id: str) -> dict[str, Any]:
    """Check du service une fois exécuté au moins une fois (Consul étale le premier sur 10 s)."""
    limite = time.monotonic() + DELAI_PREMIER_CHECK
    checks: dict[str, Any] = {}
    while time.monotonic() < limite:
        checks = (await consul.get("/v1/agent/checks")).json()
        du_service = [c for c in checks.values() if c["ServiceID"] == service_id]
        if du_service and du_service[0]["Output"]:
            return du_service[0]  # type: ignore[no-any-return]
        await anyio.sleep(1)
    raise AssertionError(f"check de {service_id} jamais exécuté : {checks}")


async def test_catalogue_s_inscrit_dans_consul_avec_ses_trois_prefixes(
    database_url: str, consul_url: str, monkeypatch: pytest.MonkeyPatch, base: Any
) -> None:
    monkeypatch.setenv("CONSUL_URL", consul_url)
    monkeypatch.delenv("TRAEFIK_POINT_ENTREE", raising=False)
    app = creer_app(
        Parametres(database_url=database_url, instance=INSTANCE, consul_actif=True),
        verificateur_jetons=EmetteurDeTest().verificateur(),
    )

    async with httpx.AsyncClient(base_url=consul_url, timeout=5.0) as consul:
        async with app.router.lifespan_context(app):
            services = (await consul.get("/v1/agent/services")).json()
            inscrits = [s for s in services.values() if s["Service"] == "catalogue"]
            assert len(inscrits) == 1, services
            inscrit = inscrits[0]
            check = await _check_execute(consul, inscrit["ID"])
        apres_arret = (await consul.get("/v1/agent/services")).json()

    assert set(inscrit["Tags"]) == TAGS_ATTENDUS
    assert check["Type"] == "http"
    assert f"http://{INSTANCE}:8000/health" in check["Output"], check["Output"]
    assert inscrit["Meta"]["metriques"] == "/metrics"
    assert inscrit["ID"] not in apres_arret
