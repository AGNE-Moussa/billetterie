"""Route d'annulation d'une séance (E1 du plan BIL-011), sans base ni Keycloak.

`POST /api/v1/events/{evenement_id}/shows/{seance_id}/cancellation` (annulerSeance) : contrôles
dans l'ordre de H2 (401, 403 rôle puis scope, 404, 409 déjà annulée avant déjà commencée).
`DepotEnMemoire.annulations_publiees` note chaque ticketing.show.cancelled publié.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from commun.faux_jetons import EmetteurDeTest

pytestmark = pytest.mark.anyio


def _route(evenement_id: UUID | str, seance_id: UUID | str) -> str:
    return f"/api/v1/events/{evenement_id}/shows/{seance_id}/cancellation"


def _assert_probleme(reponse: httpx.Response, statut: int, code: str) -> None:
    assert reponse.status_code == statut, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == code, reponse.json()


def _intacte(depot: Any, seance_id: UUID) -> None:
    assert depot.seances[seance_id].annulee is False
    assert depot.annulations_publiees == []


# --- 401 / 403 : gardes du contrat ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("jeton", "code"),
    [
        ("absent", "JETON_ABSENT"),
        ("expire", "JETON_EXPIRE"),
        ("invalide", "JETON_INVALIDE"),
    ],
)
async def test_une_annulation_sans_jeton_renvoie_401(
    anonyme: httpx.AsyncClient,
    depot: Any,
    semis: Any,
    emetteur: EmetteurDeTest,
    jeton: str,
    code: str,
) -> None:
    scopes = ["events:read", "events:write"]
    entetes: dict[str, str] = {}
    if jeton == "expire":
        entetes = emetteur.entetes(roles=["admin"], scopes=scopes, expire_dans=-3600)
    elif jeton == "invalide":
        entetes = EmetteurDeTest().entetes(roles=["admin"], scopes=scopes)

    reponse = await anonyme.post(_route(semis.evenement.id, semis.seance.id), headers=entetes)

    _assert_probleme(reponse, 401, code)
    _intacte(depot, semis.seance.id)


@pytest.mark.parametrize("appelant", ["client", "revendeur"])
async def test_un_client_ou_un_revendeur_ne_peut_pas_annuler_une_seance(
    anonyme: httpx.AsyncClient,
    depot: Any,
    semis: Any,
    emetteur: EmetteurDeTest,
    appelant: str,
) -> None:
    # Même avec events:write, le rôle manque : ROLE_MANQUANT est contrôlé d'abord (H2).
    scopes = ["events:read", "events:write"]
    entetes = (
        emetteur.entetes(roles=["customer"], scopes=scopes)
        if appelant == "client"
        else emetteur.entetes(roles=["partner"], scopes=scopes, client="revendeur-test")
    )

    reponse = await anonyme.post(_route(semis.evenement.id, semis.seance.id), headers=entetes)

    _assert_probleme(reponse, 403, "ROLE_MANQUANT")
    _intacte(depot, semis.seance.id)


async def test_un_admin_sans_scope_events_write_ne_peut_pas_annuler(
    anonyme: httpx.AsyncClient, depot: Any, semis: Any, emetteur: EmetteurDeTest
) -> None:
    entetes = emetteur.entetes(roles=["admin"], scopes=["events:read"])

    reponse = await anonyme.post(_route(semis.evenement.id, semis.seance.id), headers=entetes)

    _assert_probleme(reponse, 403, "SCOPE_MANQUANT")
    _intacte(depot, semis.seance.id)


# --- 404 / 422 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("cas", ["evenement_inconnu", "seance_inconnue", "seance_d_un_autre"])
async def test_une_seance_ou_un_evenement_inconnu_renvoie_404(
    anonyme: httpx.AsyncClient,
    depot: Any,
    semis: Any,
    entetes_admin: dict[str, str],
    cas: str,
) -> None:
    # S2 : séance d'un autre événement E2.
    e2 = depot.semer_evenement("Autre concert de test")
    s2 = depot.semer_seance(e2, semis.lieu)
    chemin, code = {
        "evenement_inconnu": (_route(uuid4(), semis.seance.id), "EVENT_NOT_FOUND"),
        "seance_inconnue": (_route(semis.evenement.id, uuid4()), "SHOW_NOT_FOUND"),
        "seance_d_un_autre": (_route(semis.evenement.id, s2.id), "SHOW_NOT_FOUND"),
    }[cas]

    reponse = await anonyme.post(chemin, headers=entetes_admin)

    _assert_probleme(reponse, 404, code)
    assert depot.seances[s2.id].annulee is False
    _intacte(depot, semis.seance.id)


async def test_un_identifiant_invalide_renvoie_422(
    anonyme: httpx.AsyncClient, depot: Any, semis: Any, entetes_admin: dict[str, str]
) -> None:
    reponse = await anonyme.post(_route(semis.evenement.id, "pas-un-uuid"), headers=entetes_admin)

    _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    _intacte(depot, semis.seance.id)


# --- 409 ------------------------------------------------------------------------------------------


async def test_annuler_une_seance_deja_annulee_renvoie_409(
    anonyme: httpx.AsyncClient, depot: Any, semis: Any, entetes_admin: dict[str, str]
) -> None:
    depot.semer_seance_annulee(semis.seance)

    reponse = await anonyme.post(_route(semis.evenement.id, semis.seance.id), headers=entetes_admin)

    _assert_probleme(reponse, 409, "SHOW_ALREADY_CANCELLED")
    assert depot.seances[semis.seance.id].annulee is True
    assert depot.annulations_publiees == []


async def test_une_seance_annulee_et_commencee_renvoie_d_abord_already_cancelled(
    anonyme: httpx.AsyncClient,
    depot: Any,
    semis: Any,
    entetes_admin: dict[str, str],
    maintenant: Any,
) -> None:
    commencee = depot.semer_seance(semis.evenement, semis.lieu, maintenant - timedelta(hours=1))
    depot.semer_seance_annulee(commencee)

    reponse = await anonyme.post(_route(semis.evenement.id, commencee.id), headers=entetes_admin)

    _assert_probleme(reponse, 409, "SHOW_ALREADY_CANCELLED")
    assert depot.annulations_publiees == []


async def test_annuler_une_seance_commencee_renvoie_409(
    anonyme: httpx.AsyncClient,
    depot: Any,
    semis: Any,
    entetes_admin: dict[str, str],
    maintenant: Any,
) -> None:
    commencee = depot.semer_seance(semis.evenement, semis.lieu, maintenant - timedelta(minutes=1))

    reponse = await anonyme.post(_route(semis.evenement.id, commencee.id), headers=entetes_admin)

    _assert_probleme(reponse, 409, "SHOW_ALREADY_STARTED")
    assert depot.seances[commencee.id].annulee is False
    assert depot.annulations_publiees == []
