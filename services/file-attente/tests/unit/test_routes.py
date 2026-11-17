"""Routes de file-attente : entrerFile, lirePositionFile, santé (BIL-015 ; review, « À couvrir »,
points 4 et 5).

Rôle `customer` seulement ; position toujours celle du `sub` du jeton ; 404 QUEUE_NOT_FOUND et
QUEUE_POSITION_NOT_FOUND ; 503 FILE_INDISPONIBLE quand Redis manque.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import anyio
import httpx
import pytest

from commun.admission import verifier_admission
from commun.faux_jetons import EmetteurDeTest

pytestmark = pytest.mark.anyio


def _chemin(seance_id: UUID) -> str:
    return f"/api/v1/queues/{seance_id}/position"


def _assert_probleme(reponse: httpx.Response, statut: int, code: str) -> None:
    assert reponse.status_code == statut, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == code


async def test_entrer_dans_la_file_repond_201_avec_la_position_puis_200_au_second_appel(
    client: httpx.AsyncClient, seance_sous_file: UUID, entetes_client: dict[str, str]
) -> None:
    premiere = await client.post(_chemin(seance_sous_file), headers=entetes_client)
    seconde = await client.post(_chemin(seance_sous_file), headers=entetes_client)

    assert premiere.status_code == 201, premiere.text
    assert premiere.json() == {
        "seance_id": str(seance_sous_file),
        "statut": "EN_ATTENTE",
        "position": 1,
        "attente_estimee_secondes": 10,
        "jeton_admission": None,
        "admission_expire_le": None,
    }
    assert seconde.status_code == 200, seconde.text
    assert seconde.json() == premiere.json()


async def test_la_position_lue_est_celle_de_l_appelant_du_jeton(
    client: httpx.AsyncClient,
    seance_sous_file: UUID,
    entetes_client: dict[str, str],
    entetes_client_b: dict[str, str],
    file_memoire: Any,
) -> None:
    await client.post(_chemin(seance_sous_file), headers=entetes_client)
    await client.post(_chemin(seance_sous_file), headers=entetes_client_b)

    reponse_b = await client.get(_chemin(seance_sous_file), headers=entetes_client_b)

    assert reponse_b.status_code == 200, reponse_b.text
    assert reponse_b.json()["position"] == 2
    assert file_memoire.attente[seance_sous_file] == ["client-a", "client-b"]


async def test_un_admis_lit_son_jeton_d_admission_valable_pour_lui_et_sa_seance(
    client: httpx.AsyncClient,
    seance_sous_file: UUID,
    entetes_client: dict[str, str],
    file_memoire: Any,
    cle_admission: str,
) -> None:
    await client.post(_chemin(seance_sous_file), headers=entetes_client)
    file_memoire.admettre(seance_sous_file, 2)

    lecture_1 = await client.get(_chemin(seance_sous_file), headers=entetes_client)
    lecture_2 = await client.get(_chemin(seance_sous_file), headers=entetes_client)
    rentree = await client.post(_chemin(seance_sous_file), headers=entetes_client)

    assert lecture_1.status_code == 200, lecture_1.text
    corps = lecture_1.json()
    assert (corps["statut"], corps["position"], corps["attente_estimee_secondes"]) == (
        "ADMIS",
        None,
        None,
    )
    assert corps["jeton_admission"] == lecture_2.json()["jeton_admission"]
    assert rentree.status_code == 200, rentree.text
    assert rentree.json()["jeton_admission"] == corps["jeton_admission"]
    verifier_admission(
        corps["jeton_admission"],
        seance_id=seance_sous_file,
        sub="client-a",
        maintenant=file_memoire.maintenant,
        cle=cle_admission,
    )


@pytest.mark.parametrize("methode", ["POST", "GET"])
async def test_une_seance_hors_file_renvoie_404_queue_not_found(
    client: httpx.AsyncClient, entetes_client: dict[str, str], file_memoire: Any, methode: str
) -> None:
    reponse = await client.request(methode, _chemin(uuid4()), headers=entetes_client)

    _assert_probleme(reponse, 404, "QUEUE_NOT_FOUND")
    assert file_memoire.attente == {}


async def test_lire_sa_position_sans_etre_entre_renvoie_404_queue_position_not_found(
    client: httpx.AsyncClient, seance_sous_file: UUID, entetes_client: dict[str, str]
) -> None:
    reponse = await client.get(_chemin(seance_sous_file), headers=entetes_client)

    _assert_probleme(reponse, 404, "QUEUE_POSITION_NOT_FOUND")


async def test_apres_expiration_de_l_admission_l_appelant_n_est_plus_dans_la_file(
    client: httpx.AsyncClient,
    seance_sous_file: UUID,
    entetes_client: dict[str, str],
    file_memoire: Any,
) -> None:
    await client.post(_chemin(seance_sous_file), headers=entetes_client)
    file_memoire.admettre(seance_sous_file, 2)
    file_memoire.maintenant += timedelta(seconds=601)

    lecture = await client.get(_chemin(seance_sous_file), headers=entetes_client)
    rentree = await client.post(_chemin(seance_sous_file), headers=entetes_client)

    _assert_probleme(lecture, 404, "QUEUE_POSITION_NOT_FOUND")
    assert rentree.status_code == 201, rentree.text
    assert rentree.json()["statut"] == "EN_ATTENTE"


@pytest.mark.parametrize("methode", ["POST", "GET"])
async def test_sans_jeton_la_file_renvoie_401(
    client: httpx.AsyncClient, seance_sous_file: UUID, file_memoire: Any, methode: str
) -> None:
    reponse = await client.request(methode, _chemin(seance_sous_file))

    _assert_probleme(reponse, 401, "JETON_ABSENT")
    assert file_memoire.attente == {}


async def test_un_jeton_d_une_autre_cle_renvoie_401(
    client: httpx.AsyncClient, seance_sous_file: UUID
) -> None:
    entetes = EmetteurDeTest().entetes(sujet="client-a", roles=["customer"])

    reponse = await client.post(_chemin(seance_sous_file), headers=entetes)

    _assert_probleme(reponse, 401, "JETON_INVALIDE")


@pytest.mark.parametrize("appelant", ["entetes_revendeur", "entetes_admin"])
@pytest.mark.parametrize("methode", ["POST", "GET"])
async def test_un_revendeur_ou_un_admin_renvoie_403_role_manquant(
    client: httpx.AsyncClient,
    seance_sous_file: UUID,
    file_memoire: Any,
    request: pytest.FixtureRequest,
    appelant: str,
    methode: str,
) -> None:
    entetes: dict[str, str] = request.getfixturevalue(appelant)

    reponse = await client.request(methode, _chemin(seance_sous_file), headers=entetes)

    _assert_probleme(reponse, 403, "ROLE_MANQUANT")
    assert file_memoire.attente == {}


async def test_un_identifiant_de_seance_invalide_renvoie_422(
    client: httpx.AsyncClient, entetes_client: dict[str, str]
) -> None:
    reponse = await client.post("/api/v1/queues/pas-un-uuid/position", headers=entetes_client)

    _assert_probleme(reponse, 422, "REQUETE_INVALIDE")


@pytest.mark.parametrize("methode", ["POST", "GET"])
async def test_redis_injoignable_renvoie_503_file_indisponible(
    client: httpx.AsyncClient,
    seance_sous_file: UUID,
    entetes_client: dict[str, str],
    file_memoire: Any,
    methode: str,
) -> None:
    file_memoire.injoignable = True

    reponse = await client.request(methode, _chemin(seance_sous_file), headers=entetes_client)

    _assert_probleme(reponse, 503, "FILE_INDISPONIBLE")


async def test_une_file_absente_renvoie_503_sur_les_routes_et_la_sante(
    fabrique_app: Any, seance_sous_file: UUID, entetes_client: dict[str, str]
) -> None:
    application = fabrique_app(file_absente=True)
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        entree = await client.post(_chemin(seance_sous_file), headers=entetes_client)
        sante = await client.get("/health")

    _assert_probleme(entree, 503, "FILE_INDISPONIBLE")
    _assert_probleme(sante, 503, "FILE_INDISPONIBLE")


async def test_la_sante_repond_ok_quand_redis_repond_et_503_sinon(
    client: httpx.AsyncClient, file_memoire: Any
) -> None:
    ok = await client.get("/health")
    file_memoire.injoignable = True
    ko = await client.get("/health")

    assert ok.status_code == 200, ok.text
    assert ok.json() == {"statut": "ok"}
    _assert_probleme(ko, 503, "FILE_INDISPONIBLE")


async def test_des_entrees_simultanees_du_meme_client_ne_creent_qu_une_place(
    client: httpx.AsyncClient,
    seance_sous_file: UUID,
    entetes_client: dict[str, str],
    file_memoire: Any,
) -> None:
    statuts: list[int] = []

    async def entrer() -> None:
        reponse = await client.post(_chemin(seance_sous_file), headers=entetes_client)
        statuts.append(reponse.status_code)

    async with anyio.create_task_group() as groupe:
        for _ in range(5):
            groupe.start_soon(entrer)

    assert sorted(statuts) == [200, 200, 200, 200, 201]
    assert file_memoire.attente[seance_sous_file] == ["client-a"]


async def test_des_clients_simultanes_recoivent_des_positions_distinctes(
    client: httpx.AsyncClient,
    seance_sous_file: UUID,
    emetteur: EmetteurDeTest,
) -> None:
    positions: list[int] = []

    async def entrer(numero: int) -> None:
        entetes = emetteur.entetes(sujet=f"client-{numero}", roles=["customer"])
        reponse = await client.post(_chemin(seance_sous_file), headers=entetes)
        assert reponse.status_code == 201, reponse.text
        positions.append(reponse.json()["position"])

    async with anyio.create_task_group() as groupe:
        for numero in range(8):
            groupe.start_soon(entrer, numero)

    assert sorted(positions) == list(range(1, 9))
