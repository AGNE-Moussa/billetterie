"""BIL-011, E1 : route d'annulation d'une séance (`annulerSeance`), sur la vraie base migrée et,
pour le cache, le vrai Redis du module (plan docs/test-plans/BIL-011.md, H2, H3).

`POST /api/v1/events/{evenement_id}/shows/{seance_id}/cancellation`, sans corps, jeton admin
(`events:write`) ; 200 `Seance` (`annulee` true), une ligne `outbox` `ticketing.show.cancelled`
dans la transaction du passage `annulee`, cache des lectures invalidé après le commit.
"""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio
import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator
from testcontainers.community.postgres import PostgresContainer

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[4]
CONTRAT = RACINE / "services" / "catalogue" / "openapi.yaml"
SCHEMA_SEANCE_ANNULEE = json.loads(
    (RACINE / "docs" / "evenements" / "ticketing.show.cancelled.json").read_text(encoding="utf-8")
)
TYPE = "ticketing.show.cancelled"
DELAI_PENDANT_LA_PAUSE = 60.0
LECTURES_DE_SEANCE = ("lireSeance", "lireSeanceParId", "listerSeances")


def chemin_annulation(evenement_id: str, seance_id: str) -> str:
    return f"/api/v1/events/{evenement_id}/shows/{seance_id}/cancellation"


@pytest.fixture(scope="module")
def composants() -> dict[str, Any]:
    contrat: dict[str, Any] = yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))
    return contrat["components"]  # type: ignore[no-any-return]


def erreurs_seance(corps: Any, composants: dict[str, Any]) -> list[str]:
    validateur = Draft202012Validator(
        {"$ref": "#/components/schemas/Seance", "components": composants},
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    return [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(corps)]


def erreurs_evenement(ligne: Any) -> list[str]:
    enveloppe = {
        "id": str(ligne["id"]),
        "type": ligne["type"],
        "version": ligne["version"],
        "occurred_at": ligne["occurred_at"].isoformat(),
        "correlation_id": ligne["correlation_id"],
        "data": ligne["data"],
    }
    validateur = Draft202012Validator(
        SCHEMA_SEANCE_ANNULEE, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    return [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(enveloppe)]


async def semer(catalogue: Any) -> tuple[str, str]:
    """Événement E et séance S (début à J+30), créés par l'API admin."""
    evenement_id = str((await catalogue.evenement())["id"])
    lieu_id = str((await catalogue.lieu())["id"])
    seance_id = str((await catalogue.seance(evenement_id, lieu_id))["id"])
    return evenement_id, seance_id


async def annulations_publiees(base: Any) -> list[Any]:
    return await base.lignes(  # type: ignore[no-any-return]
        "SELECT xmin::text AS xmin, * FROM outbox WHERE type = :type", type=TYPE
    )


async def ligne_seance(base: Any, seance_id: str) -> Any:
    lignes = await base.lignes(
        "SELECT xmin::text AS xmin, annulee FROM seances WHERE id = :id", id=UUID(seance_id)
    )
    assert len(lignes) == 1, lignes
    return lignes[0]


# --- Route ------------------------------------------------------------------------------------


async def test_un_admin_annule_une_seance_et_recoit_la_seance_annulee(
    client_admin: httpx.AsyncClient, catalogue: Any, base: Any, composants: dict[str, Any]
) -> None:
    evenement_id, seance_id = await semer(catalogue)

    reponse = await client_admin.post(chemin_annulation(evenement_id, seance_id))

    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["content-type"].startswith("application/json")
    corps = reponse.json()
    assert erreurs_seance(corps, composants) == []
    assert corps["id"] == seance_id
    assert corps["evenement_id"] == evenement_id
    assert corps["annulee"] is True
    assert (await ligne_seance(base, seance_id))["annulee"] is True


async def test_l_annulation_publie_show_cancelled_dans_la_meme_transaction(
    client_admin: httpx.AsyncClient, catalogue: Any, base: Any
) -> None:
    evenement_id, seance_id = await semer(catalogue)

    reponse = await client_admin.post(chemin_annulation(evenement_id, seance_id))

    assert reponse.status_code == 200, reponse.text
    lignes = await annulations_publiees(base)
    assert len(lignes) == 1, lignes
    (ligne,) = lignes
    assert ligne["data"] == {"seance_id": seance_id, "evenement_id": evenement_id}
    assert ligne["version"] == 1
    assert erreurs_evenement(ligne) == []
    # Même transaction : la ligne de la séance et celle de l'outbox portent le même xmin.
    assert ligne["xmin"] == (await ligne_seance(base, seance_id))["xmin"]


async def test_une_base_injoignable_renvoie_503_sans_evenement(
    client_admin: httpx.AsyncClient,
    catalogue: Any,
    base: Any,
    postgres: PostgresContainer,
    borner: Any,
) -> None:
    evenement_id, seance_id = await semer(catalogue)
    chemin = chemin_annulation(evenement_id, seance_id)
    conteneur = postgres.get_wrapped_container()

    conteneur.pause()
    try:
        pendant = await borner(
            f"POST {chemin}, base en pause",
            client_admin.post(chemin),
            DELAI_PENDANT_LA_PAUSE,
        )
    finally:
        conteneur.unpause()

    assert pendant.status_code == 503, pendant.text
    assert pendant.headers["content-type"].startswith("application/problem+json")
    assert pendant.json()["code"] == "BASE_INDISPONIBLE"
    assert await annulations_publiees(base) == []
    assert (await ligne_seance(base, seance_id))["annulee"] is False


# --- Cache des lectures (H3) ------------------------------------------------------------------


def _identifiants(chemins: dict[str, str]) -> tuple[str, str]:
    """(evenement_id, seance_id) depuis le chemin de lireSeance."""
    morceaux = chemins["lireSeance"].strip("/").split("/")
    return morceaux[3], morceaux[5]


def _seance_lue(operation: str, corps: Any, seance_id: str) -> Any:
    if operation != "listerSeances":
        return corps
    trouvees = [element for element in corps["elements"] if element["id"] == seance_id]
    assert len(trouvees) == 1, f"S absente de listerSeances : {corps}"
    return trouvees[0]


@pytest.mark.parametrize("operation", LECTURES_DE_SEANCE)
async def test_la_seance_annulee_est_lue_annulee_juste_apres_l_annulation(
    operation: str, plateforme: Any, cache_redis: Any
) -> None:
    chemins = await plateforme.semer_lectures()
    evenement_id, seance_id = _identifiants(chemins)
    avant = await plateforme.public.get(chemins[operation])
    assert avant.status_code == 200, avant.text
    assert _seance_lue(operation, avant.json(), seance_id)["annulee"] is False
    await cache_redis.exiger_rempli(f"après {operation}")

    annulation = await plateforme.admin.post(chemin_annulation(evenement_id, seance_id))
    apres = await plateforme.public.get(chemins[operation])

    assert annulation.status_code == 200, annulation.text
    assert apres.status_code == 200, apres.text
    assert _seance_lue(operation, apres.json(), seance_id)["annulee"] is True


async def test_la_copie_de_secours_ne_rend_pas_une_seance_non_annulee(
    plateforme: Any,
    cache_redis: Any,
    postgres: Any,
    en_pause: Any,
    borner: Any,
    attente_fraicheur: float,
) -> None:
    chemins = await plateforme.semer_lectures()
    evenement_id, seance_id = _identifiants(chemins)
    chemin = chemins["lireSeanceParId"]
    assert (await plateforme.public.get(chemin)).status_code == 200
    await cache_redis.exiger_rempli("après lireSeanceParId")

    annulation = await plateforme.admin.post(chemin_annulation(evenement_id, seance_id))
    assert annulation.status_code == 200, annulation.text
    # La copie fraîche a expiré : seule une copie de secours pourrait servir la lecture.
    await anyio.sleep(attente_fraicheur)
    with en_pause(postgres):
        pendant = await borner(
            f"GET {chemin}, base en pause", plateforme.public.get(chemin), plateforme.delai_lecture
        )

    assert pendant.status_code in (200, 503), pendant.text
    if pendant.status_code == 200:
        assert pendant.json()["annulee"] is True, pendant.text
    else:
        assert pendant.json()["code"] == "BASE_INDISPONIBLE"
