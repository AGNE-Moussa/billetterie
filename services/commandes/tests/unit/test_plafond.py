"""Plafond de billets par client et par séance (E2 du plan BIL-008 ; décisions Q3, Q15, Q23)."""

from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from commandes.config import Parametres
from commandes.domaine.commandes import StatutCommande

pytestmark = pytest.mark.anyio

ORDERS = "/api/v1/orders"
URL_BASE = "postgresql+asyncpg://test@127.0.0.1:5432/commandes"


def test_la_limite_par_defaut_est_de_dix_billets(
    monkeypatch: pytest.MonkeyPatch, environnement_propre: None
) -> None:
    assert Parametres(database_url=URL_BASE).limite_billets_par_seance == 10

    monkeypatch.setenv("LIMITE_BILLETS_PAR_SEANCE", "0")
    with pytest.raises(ValidationError):
        Parametres(database_url=URL_BASE)


async def test_atteindre_exactement_la_limite_est_accepte(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], depot: Any
) -> None:
    depot.semer("client-a", seance.id, StatutCommande.CONFIRMEE, lignes=6)

    reponse = await client.post(
        ORDERS, json=seance.corps("A1", "A2", "A3", "A4"), headers=entetes_a
    )

    assert reponse.status_code == 201, reponse.text


async def test_depasser_la_limite_renvoie_409_sans_creer_de_commande(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_a: dict[str, str],
    depot: Any,
    journal: Any,
) -> None:
    existante = depot.semer("client-a", seance.id, StatutCommande.EN_ATTENTE, lignes=8)

    reponse = await client.post(ORDERS, json=seance.corps("A1", "A2", "A3"), headers=entetes_a)

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["code"] == "TICKET_LIMIT_EXCEEDED"
    assert [c.id for c in depot.commandes_de("client-a")] == [existante.id]
    assert journal.de("billets") == []
    assert depot.evenements == []


async def test_les_commandes_expirees_ou_remboursees_ne_comptent_pas(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], depot: Any
) -> None:
    depot.semer("client-a", seance.id, StatutCommande.EXPIREE, lignes=5)
    depot.semer("client-a", seance.id, StatutCommande.REMBOURSEE, lignes=5)

    reponse = await client.post(ORDERS, json=seance.corps("A1", "A2"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text


async def test_la_limite_est_propre_au_client_et_a_la_seance(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], depot: Any
) -> None:
    depot.semer("client-b", seance.id, StatutCommande.CONFIRMEE, lignes=10)
    depot.semer("client-a", uuid4(), StatutCommande.CONFIRMEE, lignes=10)

    reponse = await client.post(ORDERS, json=seance.corps("A1", "A2"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text
