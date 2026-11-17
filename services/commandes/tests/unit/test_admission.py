"""Jeton d'admission exigé par creerCommande pour une séance sous file (BIL-015, CA1 ; review,
« À couvrir », points 2 et 3).

Séance hors liste : rien d'exigé. Revendeur : exempté. Client : 403 ADMISSION_REQUIRED sans
jeton, 403 ADMISSION_INVALID pour un jeton mal signé, expiré, d'une autre séance ou d'un autre
appelant ; refus avant tout appel sortant, toute commande et toute clé d'idempotence.
"""

import secrets
from datetime import timedelta
from typing import Any
from uuid import uuid4

import anyio
import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from commandes.config import Parametres
from commandes.domaine.commandes import StatutCommande
from commun.admission import LONGUEUR_MIN_CLE, signer_admission

pytestmark = pytest.mark.anyio

ORDERS = "/api/v1/orders"
URL_BASE = "postgresql+asyncpg://test@127.0.0.1:5432/commandes"
URL_REDIS = "redis://127.0.0.1:6379/0"
ENTETE = "X-Admission-Token"


@pytest.fixture
def cle() -> str:
    return secrets.token_urlsafe(48)


@pytest.fixture
def app(fabrique_app: Any, seance: Any, cle: str) -> FastAPI:
    """Séance `S` du conftest sous file d'attente."""
    return fabrique_app(seances_sous_file=frozenset({seance.id}), admission_cle_signature=cle)


@pytest.fixture
def jeton_a(seance: Any, cle: str, horloge: Any) -> str:
    """Jeton de client-a pour `S`, valable 10 min."""
    return signer_admission(seance.id, "client-a", horloge.maintenant + timedelta(minutes=10), cle)


def _sans_effet(depot: Any, journal: Any) -> None:
    assert depot.commandes == {}
    assert depot.cles_tenues == set()
    assert depot.evenements == []
    assert journal.appels == []


async def test_un_client_admis_commande_avec_son_jeton(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], jeton_a: str
) -> None:
    reponse = await client.post(
        ORDERS, json=seance.corps("A1"), headers={**entetes_a, ENTETE: jeton_a}
    )

    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["statut"] == "CONFIRMEE"


async def test_le_jeton_se_reutilise_jusqu_a_son_expiration(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], jeton_a: str
) -> None:
    entetes = {**entetes_a, ENTETE: jeton_a}

    premiere = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes)
    seconde = await client.post(ORDERS, json=seance.corps("A2"), headers=entetes)

    assert premiere.status_code == 201, premiere.text
    assert seconde.status_code == 201, seconde.text


@pytest.mark.parametrize("jeton", [None, ""])
async def test_un_client_sans_jeton_recoit_403_admission_required_sans_aucun_effet(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    journal: Any,
    jeton: str | None,
) -> None:
    entetes = {**entetes_a, "Idempotency-Key": "cle-bil-015-sans-jeton"}
    if jeton is not None:
        entetes[ENTETE] = jeton

    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes)

    assert reponse.status_code == 403, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == "ADMISSION_REQUIRED"
    _sans_effet(depot, journal)


@pytest.mark.parametrize(
    "cas", ["autre_seance", "autre_appelant", "expire", "autre_cle", "illisible", "altere"]
)
async def test_un_jeton_non_valable_recoit_403_admission_invalid_sans_aucun_effet(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    journal: Any,
    horloge: Any,
    cle: str,
    jeton_a: str,
    cas: str,
) -> None:
    echeance = horloge.maintenant + timedelta(minutes=10)
    jetons = {
        "autre_seance": signer_admission(uuid4(), "client-a", echeance, cle),
        "autre_appelant": signer_admission(seance.id, "client-b", echeance, cle),
        "expire": signer_admission(seance.id, "client-a", horloge.maintenant, cle),
        "autre_cle": signer_admission(seance.id, "client-a", echeance, secrets.token_urlsafe(48)),
        "illisible": "pas-un-jeton",
        "altere": jeton_a[:-1] + ("A" if jeton_a[-1] != "A" else "B"),
    }
    entetes = {**entetes_a, ENTETE: jetons[cas], "Idempotency-Key": "cle-bil-015-invalide"}

    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes)

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["code"] == "ADMISSION_INVALID"
    _sans_effet(depot, journal)


async def test_le_jeton_d_un_autre_client_ne_sert_pas(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_b: dict[str, str],
    jeton_a: str,
    depot: Any,
    journal: Any,
) -> None:
    reponse = await client.post(
        ORDERS, json=seance.corps("A1"), headers={**entetes_b, ENTETE: jeton_a}
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["code"] == "ADMISSION_INVALID"
    _sans_effet(depot, journal)


async def test_un_jeton_expire_pendant_l_admission_est_refuse_a_son_echeance(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    jeton_a: str,
    horloge: Any,
    depot: Any,
    journal: Any,
) -> None:
    horloge.avancer(10 * 60)

    reponse = await client.post(
        ORDERS, json=seance.corps("A1"), headers={**entetes_a, ENTETE: jeton_a}
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["code"] == "ADMISSION_INVALID"
    _sans_effet(depot, journal)


async def test_un_revendeur_n_est_pas_soumis_a_la_file(
    client: httpx.AsyncClient, seance: Any, entetes_r1: dict[str, str]
) -> None:
    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes_r1)

    assert reponse.status_code == 201, reponse.text


async def test_une_seance_hors_file_se_commande_sans_jeton(
    fabrique_app: Any,
    seance: Any,
    cle: str,
    entetes_a: dict[str, str],
) -> None:
    application = fabrique_app(seances_sous_file=frozenset({uuid4()}), admission_cle_signature=cle)
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text


async def test_un_en_tete_d_admission_de_plus_de_512_caracteres_renvoie_422(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    journal: Any,
) -> None:
    reponse = await client.post(
        ORDERS, json=seance.corps("A1"), headers={**entetes_a, ENTETE: "j" * 513}
    )

    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["code"] == "REQUETE_INVALIDE"
    _sans_effet(depot, journal)


async def test_deux_clients_admis_qui_veulent_la_meme_place_un_seul_l_obtient(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    entetes_b: dict[str, str],
    cle: str,
    horloge: Any,
    depot: Any,
) -> None:
    echeance = horloge.maintenant + timedelta(minutes=10)
    appels = [
        {**entetes_a, ENTETE: signer_admission(seance.id, "client-a", echeance, cle)},
        {**entetes_b, ENTETE: signer_admission(seance.id, "client-b", echeance, cle)},
    ]
    statuts: list[int] = []
    codes: list[str] = []

    async def commander(entetes: dict[str, str]) -> None:
        reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes)
        statuts.append(reponse.status_code)
        if reponse.status_code != 201:
            codes.append(reponse.json()["code"])

    async with anyio.create_task_group() as groupe:
        for entetes in appels:
            groupe.start_soon(commander, entetes)

    assert sorted(statuts) == [201, 409]
    assert codes == ["SEAT_ALREADY_TAKEN"]
    confirmees = [c for c in depot.commandes.values() if c.statut is StatutCommande.CONFIRMEE]
    assert len(confirmees) == 1


# --- Configuration de Commandes ------------------------------------------------------------------


@pytest.fixture
def sans_file(monkeypatch: pytest.MonkeyPatch, environnement_propre: None) -> None:
    monkeypatch.delenv("SEANCES_SOUS_FILE", raising=False)
    monkeypatch.delenv("ADMISSION_CLE_SIGNATURE", raising=False)


def test_par_defaut_aucune_seance_n_est_sous_file(sans_file: None) -> None:
    assert Parametres(database_url=URL_BASE, redis_url=URL_REDIS).seances_sous_file == frozenset()


def test_les_seances_sous_file_se_lisent_avec_espaces_et_entrees_vides(
    monkeypatch: pytest.MonkeyPatch, sans_file: None
) -> None:
    premiere, seconde = uuid4(), uuid4()
    monkeypatch.setenv("SEANCES_SOUS_FILE", f" {premiere} ,,{seconde} ,")
    monkeypatch.setenv("ADMISSION_CLE_SIGNATURE", secrets.token_urlsafe(48))

    config = Parametres(database_url=URL_BASE, redis_url=URL_REDIS)

    assert config.seances_sous_file == frozenset({premiere, seconde})


def test_un_identifiant_de_seance_invalide_est_refuse(
    monkeypatch: pytest.MonkeyPatch, sans_file: None
) -> None:
    monkeypatch.setenv("SEANCES_SOUS_FILE", "pas-un-uuid")
    monkeypatch.setenv("ADMISSION_CLE_SIGNATURE", secrets.token_urlsafe(48))

    with pytest.raises(ValidationError):
        Parametres(database_url=URL_BASE, redis_url=URL_REDIS)


@pytest.mark.parametrize("cle", [None, "c" * (LONGUEUR_MIN_CLE - 1)])
def test_une_seance_sous_file_sans_cle_ou_avec_une_cle_courte_refuse_le_demarrage(
    monkeypatch: pytest.MonkeyPatch, sans_file: None, cle: str | None
) -> None:
    monkeypatch.setenv("SEANCES_SOUS_FILE", str(uuid4()))
    if cle is not None:
        monkeypatch.setenv("ADMISSION_CLE_SIGNATURE", cle)

    with pytest.raises(ValidationError, match="ADMISSION_CLE_SIGNATURE"):
        Parametres(database_url=URL_BASE, redis_url=URL_REDIS)
