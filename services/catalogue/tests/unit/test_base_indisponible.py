"""Base injoignable : 503 BASE_INDISPONIBLE (E5, décisions Q6 et Q15 du plan BIL-004).

Sans Docker : vraie application, vrai dépôt SQL, URL de base sur le port 1 (fermé : connexion
refusée tout de suite), lifespan démarré, Consul désactivé.
"""

import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from catalogue.config import Parametres
from catalogue.principal import creer_app
from commun.faux_jetons import EmetteurDeTest

pytestmark = pytest.mark.anyio

MOT_DE_PASSE = secrets.token_urlsafe(16)
URL_FERMEE = f"postgresql+asyncpg://catalogue:{MOT_DE_PASSE}@127.0.0.1:1/catalogue"
ID = uuid4()
LECTURES = {
    "listerEvenements": "/api/v1/events",
    "lireEvenement": f"/api/v1/events/{ID}",
    "listerSeances": f"/api/v1/events/{ID}/shows",
    "lireSeance": f"/api/v1/events/{ID}/shows/{uuid4()}",
    "lireSeanceParId": f"/api/v1/shows/{ID}",
    "listerLieux": "/api/v1/venues",
    "lireLieu": f"/api/v1/venues/{ID}",
}
DEBUT = (datetime.now(UTC) + timedelta(days=30)).isoformat()
ECRITURES: dict[str, tuple[str, dict[str, Any]]] = {
    "creerEvenement": (
        "/api/v1/events",
        {"nom": "Concert de test", "description": "Description synthétique"},
    ),
    "creerLieu": (
        "/api/v1/venues",
        {"nom": "Salle de test", "adresse": "1 rue de l'Exemple", "ville": "Villetest"},
    ),
    "creerSeance": (
        f"/api/v1/events/{ID}/shows",
        {
            "lieu_id": str(uuid4()),
            "debut": DEBUT,
            "categories": [
                {"nom": "Fosse", "prix": 4500, "rangs": [{"rang": "A", "nombre_places": 10}]}
            ],
        },
    ),
}


@pytest.fixture
def emetteur() -> EmetteurDeTest:
    return EmetteurDeTest()


@pytest.fixture
async def sans_base(emetteur: EmetteurDeTest) -> AsyncIterator[httpx.AsyncClient]:
    config = Parametres(database_url=URL_FERMEE, instance="catalogue-test", consul_actif=False)
    app = creer_app(config, verificateur_jetons=emetteur.verificateur())
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        yield client


def _assert_base_indisponible(reponse: httpx.Response) -> None:
    assert reponse.status_code == 503, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme = reponse.json()
    assert probleme["code"] == "BASE_INDISPONIBLE"
    assert probleme["status"] == 503
    for fuite in ("Traceback", "127.0.0.1", MOT_DE_PASSE, "asyncpg", "postgresql"):
        assert fuite not in reponse.text


@pytest.mark.parametrize("operation", list(LECTURES))
async def test_une_lecture_sans_base_renvoie_503(
    sans_base: httpx.AsyncClient, operation: str
) -> None:
    reponse = await sans_base.get(LECTURES[operation])

    _assert_base_indisponible(reponse)


@pytest.mark.parametrize("operation", list(ECRITURES))
async def test_une_ecriture_sans_base_suit_la_regle_retenue(
    sans_base: httpx.AsyncClient, emetteur: EmetteurDeTest, operation: str
) -> None:
    # Q15 : 503 BASE_INDISPONIBLE, déclaré au contrat sur les trois créations.
    chemin, corps = ECRITURES[operation]
    entetes = emetteur.entetes(roles=["admin"], scopes=["events:read", "events:write"])

    reponse = await sans_base.post(chemin, json=corps, headers=entetes)

    _assert_base_indisponible(reponse)
