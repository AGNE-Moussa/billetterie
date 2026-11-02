"""Verrou d'une place par une commande (CA1, CA2, CA3, E1, E2 du plan BIL-006), sans Redis.

Le magasin de verrous en mémoire partage l'horloge de la requête : `horloge.avancer(...)` fait
expirer les verrous comme le ferait le PX de Redis.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

pytestmark = pytest.mark.anyio

TOLERANCE = timedelta(seconds=2)
RESERVATION = timedelta(seconds=600)
CONFIRMATION = timedelta(seconds=3600)


def _chemin(place_id: UUID | str) -> str:
    return f"/api/v1/seats/{place_id}/lock"


async def _verrouiller(
    client: httpx.AsyncClient,
    entetes: dict[str, str],
    place: Any,
    commande_id: UUID,
    *,
    confirmation: bool | None = None,
    seance_id: UUID | None = None,
) -> httpx.Response:
    corps: dict[str, Any] = {
        "seance_id": str(seance_id or place.seance_id),
        "commande_id": str(commande_id),
    }
    if confirmation is not None:
        corps["confirmation"] = confirmation
    return await client.put(_chemin(place.id), json=corps, headers=entetes)


def _assert_probleme(reponse: httpx.Response, statut: int, code: str) -> dict[str, Any]:
    assert reponse.status_code == statut, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    probleme: dict[str, Any] = reponse.json()
    assert probleme["code"] == code
    return probleme


def _assert_expire_vers(reponse: httpx.Response, attendu: datetime) -> None:
    assert reponse.status_code == 200, reponse.text
    expire_le = datetime.fromisoformat(reponse.json()["expire_le"])
    assert expire_le.utcoffset() is not None, "expire_le sans fuseau"
    assert abs(expire_le - attendu) <= TOLERANCE, (expire_le, attendu)


# --- CA1 : une place verrouillée est refusée à une autre commande --------------------------------


async def test_verrouiller_une_place_libre_renvoie_200_et_le_verrou_de_la_commande(
    client: httpx.AsyncClient,
    seance: Any,
    verrous: Any,
    horloge: Any,
    entetes_service: dict[str, str],
) -> None:
    place = seance["A1"]
    commande_a = uuid4()

    reponse = await _verrouiller(client, entetes_service, place, commande_a)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["place_id"] == str(place.id)
    assert corps["seance_id"] == str(seance.id)
    assert corps["categorie_id"] == str(seance.fosse)
    assert corps["commande_id"] == str(commande_a)
    _assert_expire_vers(reponse, horloge.maintenant + RESERVATION)
    assert verrous.detenteur(seance.id, place.id) == str(commande_a)


async def test_une_place_verrouillee_par_une_commande_est_refusee_a_une_autre_commande(
    client: httpx.AsyncClient, seance: Any, verrous: Any, entetes_service: dict[str, str]
) -> None:
    place = seance["A1"]
    commande_a, commande_b = uuid4(), uuid4()
    premiere = await _verrouiller(client, entetes_service, place, commande_a)
    assert premiere.status_code == 200, premiere.text

    reponse = await _verrouiller(client, entetes_service, place, commande_b)

    _assert_probleme(reponse, 409, "SEAT_ALREADY_TAKEN")
    assert verrous.detenteur(seance.id, place.id) == str(commande_a)


async def test_une_place_deja_vendue_est_refusee_meme_sans_verrou(
    client: httpx.AsyncClient,
    depot: Any,
    seance: Any,
    verrous: Any,
    entetes_service: dict[str, str],
) -> None:
    place = seance["A2"]
    depot.semer_billet(place)

    reponse = await _verrouiller(client, entetes_service, place, uuid4())

    _assert_probleme(reponse, 409, "SEAT_ALREADY_TAKEN")
    assert verrous.cles() == {}


# --- CA2 : le verrou expire seul après la durée fixée --------------------------------------------


async def test_apres_la_duree_de_reservation_la_place_redevient_verrouillable(
    client: httpx.AsyncClient,
    seance: Any,
    verrous: Any,
    horloge: Any,
    entetes_service: dict[str, str],
) -> None:
    place = seance["A1"]
    commande_a, commande_b = uuid4(), uuid4()
    premiere = await _verrouiller(client, entetes_service, place, commande_a)
    assert premiere.status_code == 200, premiere.text
    horloge.avancer(600.001)

    reponse = await _verrouiller(client, entetes_service, place, commande_b)

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["commande_id"] == str(commande_b)
    assert verrous.detenteur(seance.id, place.id) == str(commande_b)


async def test_avant_la_fin_de_la_duree_la_place_reste_refusee(
    client: httpx.AsyncClient,
    seance: Any,
    verrous: Any,
    horloge: Any,
    entetes_service: dict[str, str],
) -> None:
    place = seance["A1"]
    commande_a, commande_b = uuid4(), uuid4()
    premiere = await _verrouiller(client, entetes_service, place, commande_a)
    assert premiere.status_code == 200, premiere.text
    horloge.avancer(599)

    reponse = await _verrouiller(client, entetes_service, place, commande_b)

    _assert_probleme(reponse, 409, "SEAT_ALREADY_TAKEN")
    assert verrous.detenteur(seance.id, place.id) == str(commande_a)


# --- CA3 : seul le détenteur du verrou peut le confirmer -----------------------------------------


async def test_la_confirmation_par_une_autre_commande_renvoie_409(
    client: httpx.AsyncClient,
    seance: Any,
    verrous: Any,
    entetes_service: dict[str, str],
) -> None:
    place = seance["A1"]
    commande_a, commande_b = uuid4(), uuid4()
    premiere = await _verrouiller(client, entetes_service, place, commande_a)
    assert premiere.status_code == 200, premiere.text
    expiration_avant = verrous.expiration(seance.id, place.id)

    reponse = await _verrouiller(client, entetes_service, place, commande_b, confirmation=True)

    _assert_probleme(reponse, 409, "SEAT_ALREADY_TAKEN")
    assert verrous.detenteur(seance.id, place.id) == str(commande_a)
    assert verrous.expiration(seance.id, place.id) == expiration_avant


# --- E1 : idempotence, prolongation et confirmation (décision Q4) --------------------------------


async def test_un_nouvel_appel_de_la_meme_commande_renvoie_200_et_prolonge_le_verrou(
    client: httpx.AsyncClient,
    seance: Any,
    verrous: Any,
    horloge: Any,
    entetes_service: dict[str, str],
) -> None:
    place = seance["A1"]
    commande_a = uuid4()
    premiere = await _verrouiller(client, entetes_service, place, commande_a)
    assert premiere.status_code == 200, premiere.text
    horloge.avancer(300)

    reponse = await _verrouiller(client, entetes_service, place, commande_a)

    _assert_expire_vers(reponse, horloge.maintenant + RESERVATION)
    assert reponse.json()["commande_id"] == str(commande_a)
    assert verrous.detenteur(seance.id, place.id) == str(commande_a)


async def test_confirmation_vaut_faux_par_defaut(
    client: httpx.AsyncClient, seance: Any, horloge: Any, entetes_service: dict[str, str]
) -> None:
    reponse = await _verrouiller(client, entetes_service, seance["B3"], uuid4())

    _assert_expire_vers(reponse, horloge.maintenant + RESERVATION)


async def test_le_detenteur_qui_confirme_obtient_la_duree_de_confirmation(
    client: httpx.AsyncClient,
    seance: Any,
    verrous: Any,
    horloge: Any,
    entetes_service: dict[str, str],
) -> None:
    place = seance["A1"]
    commande_a = uuid4()
    premiere = await _verrouiller(client, entetes_service, place, commande_a)
    assert premiere.status_code == 200, premiere.text

    reponse = await _verrouiller(client, entetes_service, place, commande_a, confirmation=True)

    _assert_expire_vers(reponse, horloge.maintenant + CONFIRMATION)
    assert verrous.detenteur(seance.id, place.id) == str(commande_a)


async def test_confirmer_sans_detenir_de_verrou_renvoie_409(
    client: httpx.AsyncClient, seance: Any, verrous: Any, entetes_service: dict[str, str]
) -> None:
    reponse = await _verrouiller(client, entetes_service, seance["A1"], uuid4(), confirmation=True)

    _assert_probleme(reponse, 409, "SEAT_ALREADY_TAKEN")
    assert verrous.cles() == {}


async def test_une_reservation_repetee_ne_raccourcit_pas_un_verrou_confirme(
    client: httpx.AsyncClient,
    seance: Any,
    horloge: Any,
    entetes_service: dict[str, str],
) -> None:
    place = seance["A1"]
    commande_a = uuid4()
    premiere = await _verrouiller(client, entetes_service, place, commande_a)
    assert premiere.status_code == 200, premiere.text
    confirmee = await _verrouiller(client, entetes_service, place, commande_a, confirmation=True)
    _assert_expire_vers(confirmee, horloge.maintenant + CONFIRMATION)
    fin_confirmation = horloge.maintenant + CONFIRMATION

    reponse = await _verrouiller(client, entetes_service, place, commande_a, confirmation=False)

    _assert_expire_vers(reponse, fin_confirmation)


# --- E2 : réponses et erreurs de verrouillerPlace ------------------------------------------------


async def test_une_place_inconnue_renvoie_404_seat_not_found(
    client: httpx.AsyncClient, seance: Any, verrous: Any, entetes_service: dict[str, str]
) -> None:
    corps = {"seance_id": str(seance.id), "commande_id": str(uuid4())}

    reponse = await client.put(_chemin(uuid4()), json=corps, headers=entetes_service)

    _assert_probleme(reponse, 404, "SEAT_NOT_FOUND")
    assert verrous.cles() == {}


async def test_une_place_d_une_autre_seance_renvoie_404_seat_not_found(
    client: httpx.AsyncClient, seance: Any, verrous: Any, entetes_service: dict[str, str]
) -> None:
    autre_seance = uuid4()

    reponse = await _verrouiller(
        client, entetes_service, seance["A1"], uuid4(), seance_id=autre_seance
    )

    _assert_probleme(reponse, 404, "SEAT_NOT_FOUND")
    assert verrous.cles() == {}


async def test_un_identifiant_de_place_invalide_renvoie_422(
    client: httpx.AsyncClient, seance: Any, entetes_service: dict[str, str]
) -> None:
    corps = {"seance_id": str(seance.id), "commande_id": str(uuid4())}

    reponse = await client.put(_chemin("pas-un-uuid"), json=corps, headers=entetes_service)

    probleme = _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert any(e["champ"] == "path.place_id" for e in probleme["erreurs"]), probleme


@pytest.mark.parametrize(
    ("champ", "modification"),
    [
        ("commande_id", {"commande_id": None}),
        ("seance_id", {"seance_id": None}),
        ("commande_id", {"commande_id": "pas-un-uuid"}),
        ("confirmation", {"confirmation": "oui"}),
    ],
    ids=["sans-commande", "sans-seance", "commande-non-uuid", "confirmation-oui"],
)
async def test_un_corps_sans_commande_ou_sans_seance_renvoie_422(
    client: httpx.AsyncClient,
    seance: Any,
    verrous: Any,
    entetes_service: dict[str, str],
    champ: str,
    modification: dict[str, Any],
) -> None:
    place = seance["A1"]
    corps: dict[str, Any] = {"seance_id": str(seance.id), "commande_id": str(uuid4())}
    for cle, valeur in modification.items():
        if valeur is None:
            corps.pop(cle)
        else:
            corps[cle] = valeur

    reponse = await client.put(_chemin(place.id), json=corps, headers=entetes_service)

    probleme = _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert any(e["champ"] == f"body.{champ}" for e in probleme["erreurs"]), probleme
    assert verrous.cles() == {}
