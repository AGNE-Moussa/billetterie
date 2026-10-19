"""Inscription dans Consul : check vert, désenregistrement propre, retrait d'une instance tuée."""

import time
from collections.abc import Awaitable, Callable

import anyio
import httpx
import pytest
from fastapi import FastAPI
from testcontainers.core.container import DockerContainer

from commun.registre import desenregistrer, enregistrer, lifespan_registre

pytestmark = pytest.mark.anyio

NOM = "faux"
ADRESSE = "faux-service"
PORT = 5678


@pytest.fixture(autouse=True)
def variable_consul(consul_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSUL_URL", consul_url)


async def _attendre(condition: Callable[[], Awaitable[bool]], delai: float, quoi: str) -> None:
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if await condition():
            return
        await anyio.sleep(1)
    raise AssertionError(f"Délai dépassé ({delai:.0f} s) : {quoi}")


async def _statut_check(consul_url: str) -> str | None:
    async with httpx.AsyncClient(base_url=consul_url) as client:
        checks = (await client.get(f"/v1/health/checks/{NOM}")).json()
    return checks[0]["Status"] if checks else None


async def _est_enregistre(consul_url: str, identifiant: str) -> bool:
    async with httpx.AsyncClient(base_url=consul_url) as client:
        services = (await client.get("/v1/agent/services")).json()
    return identifiant in services


async def test_service_demarre_apparait_avec_check_vert(
    consul_url: str, faux_service: DockerContainer
) -> None:
    identifiant = await enregistrer(NOM, ADRESSE, PORT)

    async def check_vert() -> bool:
        return await _statut_check(consul_url) == "passing"

    await _attendre(check_vert, 30, "check passing")

    await desenregistrer(identifiant)
    assert not await _est_enregistre(consul_url, identifiant)


async def test_lifespan_enregistre_au_demarrage_et_retire_a_l_arret(
    consul_url: str, faux_service: DockerContainer
) -> None:
    app = FastAPI(lifespan=lifespan_registre(NOM, ADRESSE, PORT))
    identifiant = f"{NOM}-{ADRESSE}-{PORT}"

    async with app.router.lifespan_context(app):
        assert await _est_enregistre(consul_url, identifiant)

    assert not await _est_enregistre(consul_url, identifiant)


async def test_service_tue_passe_critique_puis_est_retire(
    consul_url: str, faux_service: DockerContainer
) -> None:
    identifiant = await enregistrer(NOM, ADRESSE, PORT)

    async def check_vert() -> bool:
        return await _statut_check(consul_url) == "passing"

    async def check_critique() -> bool:
        return await _statut_check(consul_url) == "critical"

    async def retire() -> bool:
        return not await _est_enregistre(consul_url, identifiant)

    await _attendre(check_vert, 30, "check passing")

    # Arrêt brutal : le service n'a pas le temps de se désenregistrer.
    faux_service.get_wrapped_container().kill()

    await _attendre(check_critique, 30, "check critical")
    # Consul retire l'instance après 1 min en critique, sa boucle de nettoyage passant
    # toutes les 30 s environ.
    await _attendre(retire, 150, "instance retirée du registre")
