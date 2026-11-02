"""Sécurité de verrouillerPlace (E6 du plan BIL-006, décisions Q3, Q12, Q17).

Le verrou est réservé au scope `seats:lock` (client `services`) ; le service revérifie le jeton
et ne croit jamais `X-User-Id` seul.
"""

from typing import Any
from uuid import uuid4

import httpx
import pytest

from commun.faux_jetons import EmetteurDeTest

pytestmark = pytest.mark.anyio


def _corps(place: Any) -> dict[str, str]:
    return {"seance_id": str(place.seance_id), "commande_id": str(uuid4())}


def _chemin(place_id: Any) -> str:
    return f"/api/v1/seats/{place_id}/lock"


def _assert_probleme(reponse: httpx.Response, statut: int, code: str) -> None:
    assert reponse.status_code == statut, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == code


async def test_sans_jeton_le_verrouillage_renvoie_401(
    client: httpx.AsyncClient, seance: Any, verrous: Any
) -> None:
    place = seance["A1"]

    reponse = await client.put(_chemin(place.id), json=_corps(place))

    _assert_probleme(reponse, 401, "JETON_ABSENT")
    assert reponse.headers["WWW-Authenticate"].startswith("Bearer")
    assert verrous.cles() == {}


@pytest.mark.parametrize(
    ("jeton", "code"), [("expire", "JETON_EXPIRE"), ("autre-cle", "JETON_INVALIDE")]
)
async def test_un_jeton_expire_ou_mal_signe_renvoie_401(
    client: httpx.AsyncClient,
    seance: Any,
    verrous: Any,
    emetteur: EmetteurDeTest,
    jeton: str,
    code: str,
) -> None:
    place = seance["A1"]
    entetes = (
        emetteur.entetes(client="services", scopes=["seats:lock"], expire_dans=-10)
        if jeton == "expire"
        else EmetteurDeTest().entetes(client="services", scopes=["seats:lock"])
    )

    reponse = await client.put(_chemin(place.id), json=_corps(place), headers=entetes)

    _assert_probleme(reponse, 401, code)
    assert verrous.cles() == {}


async def test_un_en_tete_x_user_id_different_du_jeton_renvoie_401(
    client: httpx.AsyncClient, seance: Any, verrous: Any, entetes_service: dict[str, str]
) -> None:
    place = seance["A1"]
    entetes = {**entetes_service, "X-User-Id": "autre-sujet-de-test"}

    reponse = await client.put(_chemin(place.id), json=_corps(place), headers=entetes)

    _assert_probleme(reponse, 401, "JETON_INVALIDE")
    assert verrous.cles() == {}


@pytest.mark.parametrize(
    "appelant",
    ["entetes_client", "entetes_revendeur", "entetes_admin", "entetes_service_sans_scope"],
)
async def test_sans_scope_seats_lock_le_verrouillage_renvoie_403(
    client: httpx.AsyncClient,
    seance: Any,
    verrous: Any,
    request: pytest.FixtureRequest,
    appelant: str,
) -> None:
    place = seance["A1"]
    entetes: dict[str, str] = request.getfixturevalue(appelant)

    reponse = await client.put(_chemin(place.id), json=_corps(place), headers=entetes)

    _assert_probleme(reponse, 403, "SCOPE_MANQUANT")
    assert verrous.cles() == {}


async def test_le_controle_d_acces_precede_la_validation_et_la_recherche_de_la_place(
    client: httpx.AsyncClient, verrous: Any, entetes_client: dict[str, str]
) -> None:
    reponse = await client.put(
        _chemin(uuid4()), json={"commande_id": "pas-un-uuid"}, headers=entetes_client
    )

    _assert_probleme(reponse, 403, "SCOPE_MANQUANT")
    assert verrous.cles() == {}


async def test_le_scope_seats_lock_suffit_quel_que_soit_le_client_du_jeton(
    client: httpx.AsyncClient, seance: Any, verrous: Any, emetteur: EmetteurDeTest
) -> None:
    place = seance["A1"]
    corps = _corps(place)
    entetes = emetteur.entetes(client="autre-client", scopes=["seats:lock"])

    reponse = await client.put(_chemin(place.id), json=corps, headers=entetes)

    assert reponse.status_code == 200, reponse.text
    assert verrous.detenteur(seance.id, place.id) == corps["commande_id"]
