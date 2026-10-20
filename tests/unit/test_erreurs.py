"""Format Problem Details (RFC 9457) produit par commun.erreurs."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from commun.correlation import MiddlewareCorrelation
from commun.erreurs import TYPE_MEDIA, ErreurMetier, installer_erreurs

pytestmark = pytest.mark.anyio

CHAMPS_RFC = {"type", "title", "status", "detail"}


class PlaceDejaPrise(ErreurMetier):
    def __init__(self, place: str) -> None:
        super().__init__("SEAT_ALREADY_TAKEN", 409, f"La place {place} est déjà prise.")


class Corps(BaseModel):
    quantite: int


def _app() -> FastAPI:
    app = FastAPI()
    installer_erreurs(app)
    app.add_middleware(MiddlewareCorrelation)

    @app.get("/places/{place}")
    async def reserver(place: str) -> None:
        raise PlaceDejaPrise(place)

    @app.post("/commandes")
    async def commander(corps: Corps) -> Corps:
        return corps

    @app.get("/panne")
    async def panne() -> None:
        raise RuntimeError("mot de passe de la base : secret-interne")

    return app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # raise_app_exceptions=False : comme uvicorn, le client reçoit le 500 au lieu de l'exception.
    transport = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_une_erreur_metier_suit_la_rfc_9457_avec_un_code_stable(
    client: httpx.AsyncClient,
) -> None:
    reponse = await client.get("/places/A12", headers={"X-Correlation-Id": "requete-1"})

    assert reponse.status_code == 409
    assert reponse.headers["content-type"] == TYPE_MEDIA
    assert reponse.json() == {
        "type": "about:blank",
        "title": "Conflict",
        "status": 409,
        "detail": "La place A12 est déjà prise.",
        "code": "SEAT_ALREADY_TAKEN",
        "correlation_id": "requete-1",
    }


async def test_une_erreur_de_validation_donne_un_422_au_meme_format(
    client: httpx.AsyncClient,
) -> None:
    reponse = await client.post("/commandes", json={"quantite": "beaucoup"})

    assert reponse.status_code == 422
    assert reponse.headers["content-type"] == TYPE_MEDIA
    probleme = reponse.json()
    assert probleme.keys() >= CHAMPS_RFC
    assert probleme["code"] == "REQUETE_INVALIDE"
    assert probleme["correlation_id"] == reponse.headers["X-Correlation-Id"]
    assert probleme["erreurs"] == [
        {"champ": "body.quantite", "message": probleme["erreurs"][0]["message"]}
    ]


async def test_une_route_inconnue_donne_un_404_au_meme_format(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/inconnue")

    assert reponse.status_code == 404
    assert reponse.headers["content-type"] == TYPE_MEDIA
    assert reponse.json()["code"] == "RESSOURCE_INTROUVABLE"


async def test_une_methode_non_prevue_donne_un_405_au_meme_format(
    client: httpx.AsyncClient,
) -> None:
    reponse = await client.delete("/commandes")

    assert reponse.status_code == 405
    assert reponse.json()["code"] == "METHODE_NON_AUTORISEE"
    assert "Allow" in reponse.headers


async def test_une_erreur_imprevue_ne_renvoie_jamais_la_trace(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    reponse = await client.get("/panne", headers={"X-Correlation-Id": "requete-panne"})

    assert reponse.status_code == 500
    assert reponse.headers["content-type"] == TYPE_MEDIA
    assert reponse.headers["X-Correlation-Id"] == "requete-panne"
    assert reponse.json() == {
        "type": "about:blank",
        "title": "Erreur interne",
        "status": 500,
        "detail": "Une erreur inattendue est survenue.",
        "code": "ERREUR_INTERNE",
        "correlation_id": "requete-panne",
    }
    assert "secret-interne" not in reponse.text
    assert "Traceback" not in reponse.text
    # La trace part dans les journaux, pour l'équipe.
    assert any(r.exc_info and "secret-interne" in str(r.exc_info[1]) for r in caplog.records)


def test_le_titre_par_defaut_est_la_phrase_du_statut() -> None:
    erreur = ErreurMetier("SEANCE_COMPLETE", 409, "Plus aucune place.")

    assert erreur.titre == "Conflict"
    assert ErreurMetier("X", 404, "d", titre="Séance introuvable").titre == "Séance introuvable"
