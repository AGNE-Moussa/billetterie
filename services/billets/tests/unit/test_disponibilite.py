"""Disponibilité des places d'une séance (E3 du plan BIL-006, décisions Q7, Q14, Q19).

Route publique : aucun en-tête Authorization. Séance commune : 27 places, rangs créés dans
l'ordre B, A, C (voir conftest).
"""

from typing import Any
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.anyio

ROUTE = "/api/v1/seats"
ORDRE_ATTENDU = (
    [f"A{n}" for n in range(1, 11)]
    + [f"B{n}" for n in range(1, 13)]
    + [f"C{n}" for n in range(1, 6)]
)


async def _toutes_les_places(client: httpx.AsyncClient, seance_id: Any) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for page in (1, 2):
        reponse = await client.get(ROUTE, params={"seance_id": str(seance_id), "page": page})
        assert reponse.status_code == 200, reponse.text
        elements += reponse.json()["elements"]
    return elements


def _disponibilites(elements: list[dict[str, Any]]) -> dict[str, bool]:
    return {f"{e['rang']}{e['numero']}": e["disponible"] for e in elements}


async def test_la_disponibilite_d_une_seance_repond_sans_jeton(
    client: httpx.AsyncClient, seance: Any
) -> None:
    reponse = await client.get(ROUTE, params={"seance_id": str(seance.id)})

    assert "Authorization" not in reponse.request.headers
    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["content-type"] == "application/json"
    corps = reponse.json()
    assert (corps["total"], corps["page"], corps["size"]) == (27, 1, 20)
    assert len(corps["elements"]) == 20
    assert all(e["disponible"] is True for e in corps["elements"])
    assert all(e["seance_id"] == str(seance.id) for e in corps["elements"])


async def test_une_place_verrouillee_est_indisponible(
    client: httpx.AsyncClient, seance: Any, verrous: Any
) -> None:
    verrous.semer(seance.id, seance["A3"].id, uuid4(), 600)

    disponibilites = _disponibilites(await _toutes_les_places(client, seance.id))

    assert len(disponibilites) == 27
    assert disponibilites["A3"] is False
    assert all(libre for nom, libre in disponibilites.items() if nom != "A3")


async def test_une_place_vendue_est_indisponible(
    client: httpx.AsyncClient, seance: Any, depot: Any
) -> None:
    depot.semer_billet(seance["B1"])

    disponibilites = _disponibilites(await _toutes_les_places(client, seance.id))

    assert len(disponibilites) == 27
    assert disponibilites["B1"] is False
    assert all(libre for nom, libre in disponibilites.items() if nom != "B1")


async def test_les_places_sont_triees_par_rang_puis_par_numero(
    client: httpx.AsyncClient, seance: Any
) -> None:
    elements = await _toutes_les_places(client, seance.id)

    assert [f"{e['rang']}{e['numero']}" for e in elements] == ORDRE_ATTENDU
    categories = {f"{e['rang']}{e['numero']}": e["categorie_id"] for e in elements}
    assert categories["A1"] == categories["B12"] == str(seance.fosse)
    assert categories["C5"] == str(seance.balcon)


async def test_une_seance_inconnue_repond_200_avec_une_page_vide(
    client: httpx.AsyncClient, seance: Any
) -> None:
    reponse = await client.get(ROUTE, params={"seance_id": str(uuid4())})

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["elements"] == []
    assert corps["total"] == 0


async def test_une_page_au_dela_de_la_fin_repond_200_vide(
    client: httpx.AsyncClient, seance: Any
) -> None:
    reponse = await client.get(ROUTE, params={"seance_id": str(seance.id), "page": 3, "size": 20})

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["elements"] == []
    assert (corps["total"], corps["page"], corps["size"]) == (27, 3, 20)


@pytest.mark.parametrize(
    ("parametres", "champ"),
    [
        ({}, "seance_id"),
        ({"seance_id": "abc"}, "seance_id"),
        ({"page": "0"}, "page"),
        ({"size": "0"}, "size"),
        ({"size": "101"}, "size"),
    ],
    ids=["sans-seance", "seance-abc", "page-0", "size-0", "size-101"],
)
async def test_une_seance_absente_ou_une_pagination_invalide_renvoie_422(
    client: httpx.AsyncClient, seance: Any, parametres: dict[str, str], champ: str
) -> None:
    requete = {"seance_id": str(seance.id)} if champ != "seance_id" else {}
    requete.update(parametres)

    reponse = await client.get(ROUTE, params=requete)

    assert reponse.status_code == 422, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme = reponse.json()
    assert probleme["code"] == "REQUETE_INVALIDE"
    assert any(e["champ"] == f"query.{champ}" for e in probleme["erreurs"]), probleme
