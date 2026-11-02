"""CA1 (BIL-004) : chaque réponse des 10 opérations métier respecte son schéma du contrat.

Depuis BIL-005 (E8), l'application est créée avec `redis_url` sur un vrai Redis (cache actif).

Base migrée, application sous lifespan ; les corps sont validés par `jsonschema` (Draft
2020-12) contre `components.schemas` de services/catalogue/openapi.yaml. Succès en
`application/json`, erreurs en `application/problem+json`, dates avec fuseau.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import yaml
from fastapi import FastAPI
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.anyio


@pytest.fixture
async def app(plateforme_cache: Any) -> AsyncIterator[FastAPI]:
    """BIL-005 (E8) : les 26 cas tournent sur l'application avec `redis_url` et un vrai Redis."""
    async with plateforme_cache() as plateforme:
        yield plateforme.app


CONTRAT = Path(__file__).resolve().parents[2] / "openapi.yaml"
CHAMPS_DATE = {"cree_le", "debut"}


@dataclass
class Contexte:
    admin: httpx.AsyncClient
    public: httpx.AsyncClient
    catalogue: Any
    jetons: Any

    async def evenement(self) -> str:
        return str((await self.catalogue.evenement())["id"])

    async def lieu(self) -> str:
        return str((await self.catalogue.lieu())["id"])

    async def seance(self) -> tuple[str, str]:
        evenement_id = await self.evenement()
        seance = await self.catalogue.seance(evenement_id, await self.lieu())
        return evenement_id, str(seance["id"])


Resultat = tuple[httpx.Response, int, str]
Cas = Callable[[Contexte], Awaitable[Resultat]]


async def _lister_evenements_200(c: Contexte) -> Resultat:
    await c.evenement()
    return await c.public.get("/api/v1/events"), 200, "EvenementPage"


async def _lister_evenements_422(c: Contexte) -> Resultat:
    return await c.public.get("/api/v1/events", params={"size": 0}), 422, "Probleme"


async def _creer_evenement_201(c: Contexte) -> Resultat:
    corps = c.catalogue.EVENEMENT
    return await c.admin.post("/api/v1/events", json=corps), 201, "Evenement"


async def _creer_evenement_401(c: Contexte) -> Resultat:
    corps = c.catalogue.EVENEMENT
    return await c.public.post("/api/v1/events", json=corps), 401, "Probleme"


async def _creer_evenement_403(c: Contexte) -> Resultat:
    reponse = await c.public.post(
        "/api/v1/events", json=c.catalogue.EVENEMENT, headers=c.jetons.client
    )
    return reponse, 403, "Probleme"


async def _creer_evenement_422(c: Contexte) -> Resultat:
    reponse = await c.admin.post("/api/v1/events", json={"description": "Sans nom"})
    return reponse, 422, "Probleme"


async def _lire_evenement_200(c: Contexte) -> Resultat:
    return await c.public.get(f"/api/v1/events/{await c.evenement()}"), 200, "Evenement"


async def _lire_evenement_404(c: Contexte) -> Resultat:
    return await c.public.get(f"/api/v1/events/{uuid4()}"), 404, "Probleme"


async def _lire_evenement_422(c: Contexte) -> Resultat:
    return await c.public.get("/api/v1/events/pas-un-uuid"), 422, "Probleme"


async def _lister_seances_200(c: Contexte) -> Resultat:
    evenement_id, _ = await c.seance()
    return await c.public.get(f"/api/v1/events/{evenement_id}/shows"), 200, "SeancePage"


async def _lister_seances_404(c: Contexte) -> Resultat:
    return await c.public.get(f"/api/v1/events/{uuid4()}/shows"), 404, "Probleme"


async def _lister_seances_422(c: Contexte) -> Resultat:
    chemin = f"/api/v1/events/{uuid4()}/shows"
    return await c.public.get(chemin, params={"page": 0}), 422, "Probleme"


async def _creer_seance_201(c: Contexte) -> Resultat:
    evenement_id, lieu_id = await c.evenement(), await c.lieu()
    reponse = await c.admin.post(
        f"/api/v1/events/{evenement_id}/shows", json=c.catalogue.corps_seance(lieu_id)
    )
    return reponse, 201, "Seance"


async def _creer_seance_404(c: Contexte) -> Resultat:
    lieu_id = await c.lieu()
    reponse = await c.admin.post(
        f"/api/v1/events/{uuid4()}/shows", json=c.catalogue.corps_seance(lieu_id)
    )
    return reponse, 404, "Probleme"


async def _creer_seance_422(c: Contexte) -> Resultat:
    evenement_id, lieu_id = await c.evenement(), await c.lieu()
    passe = c.catalogue.instant(minutes=-1)
    reponse = await c.admin.post(
        f"/api/v1/events/{evenement_id}/shows", json=c.catalogue.corps_seance(lieu_id, passe)
    )
    return reponse, 422, "Probleme"


async def _lire_seance_200(c: Contexte) -> Resultat:
    evenement_id, seance_id = await c.seance()
    chemin = f"/api/v1/events/{evenement_id}/shows/{seance_id}"
    return await c.public.get(chemin), 200, "Seance"


async def _lire_seance_404(c: Contexte) -> Resultat:
    chemin = f"/api/v1/events/{await c.evenement()}/shows/{uuid4()}"
    return await c.public.get(chemin), 404, "Probleme"


async def _lire_seance_par_id_200(c: Contexte) -> Resultat:
    _, seance_id = await c.seance()
    return await c.public.get(f"/api/v1/shows/{seance_id}"), 200, "Seance"


async def _lire_seance_par_id_404(c: Contexte) -> Resultat:
    return await c.public.get(f"/api/v1/shows/{uuid4()}"), 404, "Probleme"


async def _lister_lieux_200(c: Contexte) -> Resultat:
    await c.lieu()
    return await c.public.get("/api/v1/venues"), 200, "LieuPage"


async def _lister_lieux_422(c: Contexte) -> Resultat:
    return await c.public.get("/api/v1/venues", params={"size": 101}), 422, "Probleme"


async def _creer_lieu_201(c: Contexte) -> Resultat:
    return await c.admin.post("/api/v1/venues", json=c.catalogue.LIEU), 201, "Lieu"


async def _creer_lieu_422(c: Contexte) -> Resultat:
    corps = {**c.catalogue.LIEU, "ville": ""}
    return await c.admin.post("/api/v1/venues", json=corps), 422, "Probleme"


async def _lire_lieu_200(c: Contexte) -> Resultat:
    return await c.public.get(f"/api/v1/venues/{await c.lieu()}"), 200, "Lieu"


async def _lire_lieu_404(c: Contexte) -> Resultat:
    return await c.public.get(f"/api/v1/venues/{uuid4()}"), 404, "Probleme"


async def _lire_lieu_422(c: Contexte) -> Resultat:
    return await c.public.get("/api/v1/venues/pas-un-uuid"), 422, "Probleme"


CAS: dict[str, Cas] = {
    "listerEvenements-200": _lister_evenements_200,
    "listerEvenements-422": _lister_evenements_422,
    "creerEvenement-201": _creer_evenement_201,
    "creerEvenement-401": _creer_evenement_401,
    "creerEvenement-403": _creer_evenement_403,
    "creerEvenement-422": _creer_evenement_422,
    "lireEvenement-200": _lire_evenement_200,
    "lireEvenement-404": _lire_evenement_404,
    "lireEvenement-422": _lire_evenement_422,
    "listerSeances-200": _lister_seances_200,
    "listerSeances-404": _lister_seances_404,
    "listerSeances-422": _lister_seances_422,
    "creerSeance-201": _creer_seance_201,
    "creerSeance-404": _creer_seance_404,
    "creerSeance-422": _creer_seance_422,
    "lireSeance-200": _lire_seance_200,
    "lireSeance-404": _lire_seance_404,
    "lireSeanceParId-200": _lire_seance_par_id_200,
    "lireSeanceParId-404": _lire_seance_par_id_404,
    "listerLieux-200": _lister_lieux_200,
    "listerLieux-422": _lister_lieux_422,
    "creerLieu-201": _creer_lieu_201,
    "creerLieu-422": _creer_lieu_422,
    "lireLieu-200": _lire_lieu_200,
    "lireLieu-404": _lire_lieu_404,
    "lireLieu-422": _lire_lieu_422,
}


@pytest.fixture(scope="module")
def composants() -> dict[str, Any]:
    contrat: dict[str, Any] = yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))
    return contrat["components"]  # type: ignore[no-any-return]


def _dates_sans_fuseau(valeur: Any, chemin: str = "$") -> list[str]:
    """Chemins des champs de date (cree_le, debut) dont la valeur n'a pas de fuseau."""
    fautifs: list[str] = []
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            if cle in CHAMPS_DATE and datetime.fromisoformat(sous_valeur).tzinfo is None:
                fautifs.append(f"{chemin}.{cle}")
            fautifs += _dates_sans_fuseau(sous_valeur, f"{chemin}.{cle}")
    elif isinstance(valeur, list):
        for indice, element in enumerate(valeur):
            fautifs += _dates_sans_fuseau(element, f"{chemin}[{indice}]")
    return fautifs


@pytest.mark.parametrize("cas", list(CAS), ids=list(CAS))
async def test_chaque_reponse_respecte_le_schema_du_contrat(
    cas: str,
    composants: dict[str, Any],
    client_admin: httpx.AsyncClient,
    client_public: httpx.AsyncClient,
    catalogue: Any,
    jetons: Any,
) -> None:
    contexte = Contexte(client_admin, client_public, catalogue, jetons)

    reponse, statut, schema = await CAS[cas](contexte)

    assert reponse.status_code == statut, reponse.text
    type_attendu = "application/json" if statut < 400 else "application/problem+json"
    assert reponse.headers["content-type"].startswith(type_attendu)
    corps = reponse.json()
    validateur = Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema}", "components": composants}
    )
    erreurs = [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(corps)]
    assert erreurs == [], erreurs
    assert _dates_sans_fuseau(corps) == []
