"""Identifiant de corrélation (commun.correlation) : en-tête, ContextVar et journaux JSON."""

import io
import json
import logging
import re
from collections.abc import AsyncIterator, Iterator

import anyio
import httpx
import pytest
from fastapi import FastAPI

from commun.correlation import (
    FormatJson,
    MiddlewareCorrelation,
    configurer_journaux,
    correlation_id,
)

pytestmark = pytest.mark.anyio

UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
journal = logging.getLogger("tests.correlation")


@pytest.fixture
def sortie() -> Iterator[io.StringIO]:
    """Journaux JSON capturés comme en production, puis gestionnaire retiré."""
    configurer_journaux()
    flux = io.StringIO()
    gestionnaire = logging.StreamHandler(flux)
    gestionnaire.setFormatter(FormatJson())
    racine = logging.getLogger()
    racine.addHandler(gestionnaire)
    yield flux
    racine.removeHandler(gestionnaire)


def _lignes(flux: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(ligne) for ligne in flux.getvalue().splitlines()]


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(MiddlewareCorrelation)

    @app.get("/identifiant")
    async def identifiant() -> dict[str, str | None]:
        journal.info("Traitement de la requête")
        await anyio.sleep(0.01)  # laisse les autres requêtes avancer entre-temps
        journal.info("Fin du traitement")
        return {"correlation_id": correlation_id()}

    return app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_l_identifiant_recu_est_conserve_et_renvoye(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/identifiant", headers={"X-Correlation-Id": "abc-123"})

    assert reponse.headers["X-Correlation-Id"] == "abc-123"
    assert reponse.json() == {"correlation_id": "abc-123"}


@pytest.mark.parametrize("recu", [None, "", "a b", "x\nfausse-ligne", "x" * 129])
async def test_un_identifiant_absent_ou_invalide_est_remplace(
    client: httpx.AsyncClient, recu: str | None
) -> None:
    entetes = {} if recu is None else {"X-Correlation-Id": recu}

    reponse = await client.get("/identifiant", headers=entetes)

    cree = reponse.headers["X-Correlation-Id"]
    assert UUID4.fullmatch(cree)
    assert reponse.json() == {"correlation_id": cree}


async def test_chaque_ligne_de_journal_porte_l_identifiant_de_sa_requete(
    client: httpx.AsyncClient, sortie: io.StringIO
) -> None:
    async def appel(numero: int) -> None:
        await client.get("/identifiant", headers={"X-Correlation-Id": f"requete-{numero}"})

    # Requêtes simultanées : chacune doit garder son propre identifiant.
    async with anyio.create_task_group() as groupe:
        for numero in range(5):
            groupe.start_soon(appel, numero)

    lignes = [ligne for ligne in _lignes(sortie) if ligne["journal"] == "tests.correlation"]
    assert len(lignes) == 10
    par_requete: dict[object, list[object]] = {}
    for ligne in lignes:
        par_requete.setdefault(ligne["correlation_id"], []).append(ligne["message"])
    assert sorted(par_requete) == [f"requete-{numero}" for numero in range(5)]
    for messages in par_requete.values():
        assert messages == ["Traitement de la requête", "Fin du traitement"]


def test_format_json_d_une_ligne(sortie: io.StringIO) -> None:
    try:
        raise ValueError("boum")
    except ValueError:
        journal.exception("Échec")

    ligne = _lignes(sortie)[-1]
    assert ligne["niveau"] == "ERROR"
    assert ligne["message"] == "Échec"
    assert ligne["correlation_id"] is None  # hors requête
    assert "ValueError: boum" in str(ligne["exception"])
    assert {"horodatage", "journal"} <= ligne.keys()


def test_configurer_deux_fois_n_ajoute_pas_de_second_gestionnaire() -> None:
    configurer_journaux()
    avant = len(logging.getLogger().handlers)
    configurer_journaux()

    assert len(logging.getLogger().handlers) == avant
    assert not logging.getLogger("uvicorn.access").handlers
