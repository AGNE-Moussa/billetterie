"""E7 (BIL-004, décisions Q17 et S2) : jeu de données de démonstration.

Chargé comme par `make demo` : `python -m catalogue.demo` avec `DATABASE_URL` sur la base
migrée du module. Attendus de Q17 : chargement par le domaine (donc par l'outbox), dates
relatives au jour du chargement, au moins deux villes, deux lieux, trois événements, cinq
séances, dont un événement sans séance ; idempotent (S2 : UUID fixes, élément existant sauté).
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.anyio

TYPE = "ticketing.show.scheduled"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[4] / "docs" / "evenements" / f"{TYPE}.json").read_text(
        encoding="utf-8"
    )
)
DELAI_CHARGEMENT = 120


def _charger(database_url: str) -> None:
    environnement = {**os.environ, "DATABASE_URL": database_url}
    try:
        resultat = subprocess.run(
            [sys.executable, "-m", "catalogue.demo"],
            env=environnement,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=DELAI_CHARGEMENT,
            check=False,
        )
    except subprocess.TimeoutExpired as depasse:
        raise AssertionError(
            f"python -m catalogue.demo : échéance de {DELAI_CHARGEMENT} s dépassée ;"
            f" sortie d'erreur : {depasse.stderr!r}"
        ) from None
    assert resultat.returncode == 0, resultat.stderr


async def _charger_demo(database_url: str) -> None:
    await anyio.to_thread.run_sync(_charger, database_url)


async def _lire(client: httpx.AsyncClient, chemin: str, **parametres: Any) -> dict[str, Any]:
    reponse = await client.get(chemin, params=parametres)
    assert reponse.status_code == 200, f"GET {chemin} : {reponse.status_code} {reponse.text}"
    corps: dict[str, Any] = reponse.json()
    return corps


async def _contenu(client: httpx.AsyncClient) -> dict[str, Any]:
    """Événements, lieux et séances relus par l'API publique."""
    evenements = await _lire(client, "/api/v1/events", size=100)
    lieux = await _lire(client, "/api/v1/venues", size=100)
    seances: dict[str, list[dict[str, Any]]] = {}
    for evenement in evenements["elements"]:
        page = await _lire(client, f"/api/v1/events/{evenement['id']}/shows", size=100)
        seances[evenement["id"]] = page["elements"]
    return {"evenements": evenements, "lieux": lieux, "seances": seances}


async def test_le_jeu_de_demonstration_se_charge_sur_une_base_migree(
    database_url: str, client_public: httpx.AsyncClient, base: Any
) -> None:
    avant_chargement = datetime.now(UTC)

    await _charger_demo(database_url)

    contenu = await _contenu(client_public)
    evenements, lieux, seances = contenu["evenements"], contenu["lieux"], contenu["seances"]
    toutes = [seance for liste in seances.values() for seance in liste]
    assert evenements["total"] >= 3, evenements
    assert lieux["total"] >= 2, lieux
    assert len({lieu["ville"] for lieu in lieux["elements"]}) >= 2
    assert len(toutes) >= 5
    assert any(not liste for liste in seances.values()), "aucun événement sans séance"
    assert all(datetime.fromisoformat(s["debut"]) > avant_chargement for s in toutes)
    assert await base.compter("seances") == len(toutes)


async def test_le_jeu_de_demonstration_se_recharge_sans_doublon(
    database_url: str, base: Any
) -> None:
    await _charger_demo(database_url)
    premier = await base.effectifs()

    await _charger_demo(database_url)

    assert premier["evenements"] > 0, premier
    assert await base.effectifs() == premier


async def test_le_jeu_de_demonstration_publie_ses_seances(database_url: str, base: Any) -> None:
    await _charger_demo(database_url)

    seances = {str(ligne["id"]) for ligne in await base.lignes("SELECT id FROM seances")}
    lignes = [ligne for ligne in await base.outbox() if ligne["type"] == TYPE]
    assert len(seances) >= 5, seances
    assert len(lignes) == len(seances)
    assert {ligne["data"]["seance_id"] for ligne in lignes} == seances
    validateur = Draft202012Validator(
        SCHEMA["properties"]["data"], format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    for ligne in lignes:
        assert [e.message for e in validateur.iter_errors(ligne["data"])] == []


async def test_le_jeu_de_demonstration_exerce_les_filtres(
    database_url: str, client_public: httpx.AsyncClient, base: Any
) -> None:
    await _charger_demo(database_url)
    contenu = await _contenu(client_public)
    total = contenu["evenements"]["total"]
    assert total > 0, "jeu de démonstration vide"

    villes = {lieu["ville"] for lieu in contenu["lieux"]["elements"]}
    par_ville = {
        ville: (await _lire(client_public, "/api/v1/events", ville=ville))["total"]
        for ville in villes
    }
    mots = {
        mot
        for evenement in contenu["evenements"]["elements"]
        for mot in evenement["nom"].split()
        if len(mot) >= 3
    }
    par_mot = {mot: (await _lire(client_public, "/api/v1/events", q=mot))["total"] for mot in mots}

    assert any(0 < nombre < total for nombre in par_ville.values()), par_ville
    assert any(0 < nombre < total for nombre in par_mot.values()), par_mot
