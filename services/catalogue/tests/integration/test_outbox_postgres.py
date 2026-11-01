"""E6 (BIL-004) : `creerSeance` range `ticketing.show.scheduled` dans l'outbox, dans la
transaction de la séance (décision Q5). Vraie base migrée, sans RabbitMQ : les lignes restent
en attente (`envoye_le` NULL).
"""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import anyio
import httpx
import pytest
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.anyio

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[4]
        / "docs"
        / "evenements"
        / "ticketing.show.scheduled.json"
    ).read_text(encoding="utf-8")
)
TYPE = "ticketing.show.scheduled"
SEANCES_SIMULTANEES = 20


def _erreurs_schema(ligne: Any) -> list[str]:
    """Écarts entre l'événement relu dans l'outbox et docs/evenements/<type>.json."""
    evenement = {
        "id": str(ligne["id"]),
        "type": ligne["type"],
        "version": ligne["version"],
        "occurred_at": ligne["occurred_at"].isoformat(),
        "correlation_id": ligne["correlation_id"],
        "data": ligne["data"],
    }
    validateur = Draft202012Validator(SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER)
    return [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(evenement)]


async def test_une_seance_creee_range_son_evenement_dans_l_outbox(
    client_admin: httpx.AsyncClient, catalogue: Any, base: Any
) -> None:
    evenement = await catalogue.evenement()
    lieu = await catalogue.lieu()

    reponse = await client_admin.post(
        f"/api/v1/events/{evenement['id']}/shows",
        json=catalogue.corps_seance(lieu["id"]),
        headers={"X-Correlation-Id": "correlation-bil-004-1"},
    )

    assert reponse.status_code == 201, reponse.text
    seance = reponse.json()
    lignes = await base.outbox()
    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne["type"] == TYPE
    assert ligne["version"] == 1
    assert ligne["correlation_id"] == "correlation-bil-004-1"
    assert ligne["envoye_le"] is None
    assert ligne["data"]["seance_id"] == seance["id"]
    assert ligne["data"]["evenement_id"] == evenement["id"]
    assert ligne["data"]["evenement_nom"] == "Concert de test"
    assert ligne["data"]["lieu_id"] == lieu["id"]
    assert ligne["data"]["lieu_nom"] == "Salle de test"
    assert ligne["data"]["ville"] == "Villetest"
    assert [c["categorie_id"] for c in ligne["data"]["categories"]] == [
        c["id"] for c in seance["categories"]
    ]
    assert _erreurs_schema(ligne) == []


REFUS = ["SHOW_START_IN_PAST", "ROW_ALREADY_ASSIGNED", "VENUE_NOT_FOUND", "EVENT_NOT_FOUND", "403"]


@pytest.mark.parametrize("refus", REFUS)
async def test_une_seance_refusee_ne_publie_rien(
    refus: str,
    client_admin: httpx.AsyncClient,
    catalogue: Any,
    jetons: Any,
    base: Any,
) -> None:
    evenement_id = (await catalogue.evenement())["id"]
    lieu_id = (await catalogue.lieu())["id"]
    corps = catalogue.corps_seance(lieu_id)
    entetes: dict[str, str] = {}
    statut, code = 422, refus
    if refus == "SHOW_START_IN_PAST":
        corps = catalogue.corps_seance(lieu_id, catalogue.instant(minutes=-1))
    elif refus == "ROW_ALREADY_ASSIGNED":
        rangs = [{"rang": "A", "nombre_places": 10}, {"rang": "A", "nombre_places": 12}]
        corps = catalogue.corps_seance(
            lieu_id, categories=[{"nom": "Fosse", "prix": 4500, "rangs": rangs}]
        )
    elif refus == "VENUE_NOT_FOUND":
        corps = catalogue.corps_seance(str(uuid4()))
        statut = 404
    elif refus == "EVENT_NOT_FOUND":
        evenement_id = str(uuid4())
        statut = 404
    else:
        entetes = jetons.client
        statut, code = 403, "SCOPE_MANQUANT"
    avant = await base.effectifs()

    reponse = await client_admin.post(
        f"/api/v1/events/{evenement_id}/shows", json=corps, headers=entetes
    )

    assert reponse.status_code == statut, reponse.text
    assert reponse.json()["code"] == code
    apres = await base.effectifs()
    for table in ("seances", "categories", "rangs", "outbox"):
        assert apres[table] == avant[table], table


async def test_un_echec_d_ecriture_dans_l_outbox_annule_la_seance(
    client_admin: httpx.AsyncClient, catalogue: Any, base: Any
) -> None:
    await base.exiger_tables()
    evenement_id = (await catalogue.evenement())["id"]
    lieu_id = (await catalogue.lieu())["id"]
    await base.executer(
        "CREATE OR REPLACE FUNCTION echec_outbox_de_test() RETURNS trigger LANGUAGE plpgsql"
        " AS $$ BEGIN RAISE EXCEPTION 'echec outbox de test'; END $$"
    )
    await base.executer(
        "CREATE TRIGGER echec_outbox_de_test BEFORE INSERT ON outbox"
        " FOR EACH ROW EXECUTE FUNCTION echec_outbox_de_test()"
    )
    try:
        reponse = await client_admin.post(
            f"/api/v1/events/{evenement_id}/shows", json=catalogue.corps_seance(lieu_id)
        )
    finally:
        await base.executer("DROP TRIGGER IF EXISTS echec_outbox_de_test ON outbox")
        await base.executer("DROP FUNCTION IF EXISTS echec_outbox_de_test()")

    assert reponse.status_code >= 500, reponse.text
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert "Traceback" not in reponse.text
    assert "echec outbox de test" not in reponse.text
    assert await base.compter("seances") == 0
    assert await base.compter("categories") == 0
    assert await base.compter("rangs") == 0
    assert await base.compter("outbox") == 0


async def test_la_creation_d_un_evenement_ou_d_un_lieu_ne_publie_rien(
    client_admin: httpx.AsyncClient, catalogue: Any, base: Any
) -> None:
    evenement = await client_admin.post("/api/v1/events", json=catalogue.EVENEMENT)
    lieu = await client_admin.post("/api/v1/venues", json=catalogue.LIEU)

    assert evenement.status_code == 201, evenement.text
    assert lieu.status_code == 201, lieu.text
    assert await base.compter("outbox") == 0


async def test_des_seances_creees_simultanement_publient_chacune_un_evenement(
    client_admin: httpx.AsyncClient, catalogue: Any, base: Any
) -> None:
    evenement_id = (await catalogue.evenement())["id"]
    lieu_id = (await catalogue.lieu())["id"]
    categories = [{"nom": "Fosse", "prix": 4500, "rangs": [{"rang": "A", "nombre_places": 10}]}]
    reponses: list[httpx.Response] = []

    async def creer(numero: int) -> None:
        corps = catalogue.corps_seance(lieu_id, catalogue.instant(10 + numero), categories)
        reponses.append(await client_admin.post(f"/api/v1/events/{evenement_id}/shows", json=corps))

    with anyio.fail_after(120):
        async with anyio.create_task_group() as groupe:
            for numero in range(SEANCES_SIMULTANEES):
                groupe.start_soon(creer, numero)

    statuts = sorted(reponse.status_code for reponse in reponses)
    assert statuts == [201] * SEANCES_SIMULTANEES, [r.text for r in reponses[:3]]
    creees = {reponse.json()["id"] for reponse in reponses}
    en_base = {str(ligne["id"]) for ligne in await base.lignes("SELECT id FROM seances")}
    lignes = await base.outbox()
    assert len(creees) == len(en_base) == SEANCES_SIMULTANEES
    assert en_base == creees
    assert len({ligne["id"] for ligne in lignes}) == len(lignes) == SEANCES_SIMULTANEES
    publiees = [ligne["data"]["seance_id"] for ligne in lignes]
    assert sorted(publiees) == sorted(creees)
