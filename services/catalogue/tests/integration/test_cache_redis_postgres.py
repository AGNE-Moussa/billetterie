"""E1, E4, E5, E7 (BIL-005) : ce que le cache garde dans Redis, et pour combien de temps.

Les tests n'inspectent que les clés du préfixe `catalogue:cache:` (SCAN, Q10) ; Redis est vidé
après la mise en place des données, pour que seules les lectures du cas le remplissent.
"""

import copy
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import anyio
import pytest
import yaml
from jsonschema import Draft202012Validator

from catalogue.config import DUREE_FRAICHE_PAR_DEFAUT

pytestmark = pytest.mark.anyio

CONTRAT = Path(__file__).resolve().parents[2] / "openapi.yaml"
# Schémas des corps 200 des 7 lectures publiques (contrat).
SCHEMAS_DES_LECTURES = ("Evenement", "EvenementPage", "Seance", "SeancePage", "Lieu", "LieuPage")


def _champs(valeur: Any) -> set[str]:
    """Noms de tous les champs d'un JSON, à toute profondeur."""
    if isinstance(valeur, dict):
        return set(valeur) | {nom for sous in valeur.values() for nom in _champs(sous)}
    if isinstance(valeur, list):
        return {nom for element in valeur for nom in _champs(element)}
    return set()


@pytest.fixture(scope="module")
def composants_stricts() -> dict[str, Any]:
    """`components` du contrat, avec `additionalProperties: false` sur chaque objet."""
    contrat = yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))
    composants: dict[str, Any] = copy.deepcopy(contrat["components"])
    for schema in composants["schemas"].values():
        if schema.get("type") == "object" and "properties" in schema:
            schema["additionalProperties"] = False
    return composants


# --- E1 : cache-aside, fraîcheur courte -----------------------------------------------------


async def test_une_modification_directe_en_base_n_est_visible_qu_apres_la_duree_de_fraicheur(
    plateforme: Any, base: Any, attente_fraicheur: float
) -> None:
    evenement = await plateforme.catalogue.evenement()
    chemin = f"/api/v1/events/{evenement['id']}"
    assert (await plateforme.public.get(chemin)).status_code == 200
    await base.executer(
        "UPDATE evenements SET nom = :nom WHERE id = :id",
        nom="Nom modifié",
        id=UUID(evenement["id"]),
    )

    aussitot = await plateforme.public.get(chemin)
    await anyio.sleep(attente_fraicheur)
    apres = await plateforme.public.get(chemin)

    assert aussitot.status_code == 200, aussitot.text
    assert aussitot.json()["nom"] == evenement["nom"]
    assert apres.status_code == 200, apres.text
    assert apres.json()["nom"] == "Nom modifié"


async def test_chaque_cle_du_cache_porte_une_expiration(
    plateforme_cache: Any, cache_redis: Any
) -> None:
    # Fraîcheur longue : aucune copie fraîche n'expire entre le SCAN et le PTTL.
    async with plateforme_cache(cache_duree_fraiche=DUREE_FRAICHE_PAR_DEFAUT) as p:
        chemins = await p.semer_lectures()
        await cache_redis.vider()
        for chemin in chemins.values():
            assert (await p.public.get(chemin)).status_code == 200, chemin
        expirations = await cache_redis.expirations_ms()

    assert len(expirations) >= len(chemins), (
        f"{len(expirations)} clé(s) {cache_redis.prefixe}* après {len(chemins)} lectures"
    )
    sans_expiration = {cle: pttl for cle, pttl in expirations.items() if pttl <= 0}
    assert sans_expiration == {}


# --- E4 : /health n'est pas mis en cache ----------------------------------------------------


async def test_la_sante_n_ecrit_rien_dans_redis(plateforme: Any, cache_redis: Any) -> None:
    for _ in range(3):
        sante = await plateforme.public.get("/health")
        assert sante.status_code == 200, sante.text

    cles_apres_sante = await cache_redis.cles()
    assert cles_apres_sante == []
    # Témoin : une lecture publique, elle, écrit dans le cache (sinon le SCAN ne prouve rien).
    assert (await plateforme.public.get("/api/v1/venues")).status_code == 200
    await cache_redis.exiger_rempli("après GET /api/v1/venues")


# --- E5 : seuls les 200 sont mis en cache ---------------------------------------------------


async def test_un_404_ne_laisse_aucune_cle_dans_redis(plateforme: Any, cache_redis: Any) -> None:
    avant = await cache_redis.cles()
    for chemin in (
        f"/api/v1/events/{uuid4()}",
        f"/api/v1/shows/{uuid4()}",
        f"/api/v1/venues/{uuid4()}",
    ):
        reponse = await plateforme.public.get(chemin)
        assert reponse.status_code == 404, f"GET {chemin} : {reponse.text}"

    assert await cache_redis.cles() == avant
    # Témoin : un 200 écrit bien dans le cache (sinon le nombre de clés ne prouve rien).
    assert (await plateforme.public.get("/api/v1/venues")).status_code == 200
    await cache_redis.exiger_rempli("après GET /api/v1/venues")


# --- E7 : aucune disponibilité des places en cache ------------------------------------------


async def test_aucune_valeur_du_cache_ne_contient_de_disponibilite_des_places(
    plateforme_cache: Any, cache_redis: Any, composants_stricts: dict[str, Any]
) -> None:
    async with plateforme_cache(cache_duree_fraiche=DUREE_FRAICHE_PAR_DEFAUT) as p:
        chemins = await p.semer_lectures()
        await cache_redis.vider()
        for chemin in chemins.values():
            assert (await p.public.get(chemin)).status_code == 200, chemin
        valeurs = await cache_redis.valeurs()

    assert len(valeurs) >= len(chemins), (
        f"{len(valeurs)} clé(s) {cache_redis.prefixe}* après {len(chemins)} lectures"
    )
    validateurs = {
        nom: Draft202012Validator(
            {"$ref": f"#/components/schemas/{nom}", "components": composants_stricts}
        )
        for nom in SCHEMAS_DES_LECTURES
    }
    fautives: dict[str, str] = {}
    for cle, brute in valeurs.items():
        try:
            corps = json.loads(brute)
        except (TypeError, ValueError):
            fautives[cle] = f"pas un JSON : {brute!r:.80}"
            continue
        if not any(validateur.is_valid(corps) for validateur in validateurs.values()):
            fautives[cle] = f"conforme à aucun des schémas {SCHEMAS_DES_LECTURES} (stricts)"
        elif disponibilites := sorted(c for c in _champs(corps) if "disponib" in c.lower()):
            fautives[cle] = f"champs de disponibilité : {disponibilites}"
    assert fautives == {}
