"""Commandes d'une séance annulée et remboursements (CA1, Commandes, du plan BIL-011), sans base.

`expirer_commandes_de_la_seance` et `enregistrer_remboursement` (domaine.annulation) appelées
directement, avec `DepotEnMemoire` (ports `DepotCommandes` et `DepotAnnulation`). Le modèle
l'emporte sur le ticket (H1) : `EN_ATTENTE` → `EXPIREE` avec ticketing.order.expired ;
`CONFIRMEE` → `REMBOURSEE` à ticketing.payment.refunded.
"""

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import jsonschema
import pytest

from commandes.domaine.annulation import enregistrer_remboursement, expirer_commandes_de_la_seance
from commandes.domaine.commandes import Commande, StatutCommande

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[4]
EVENEMENT_COMMANDE_EXPIREE = "ticketing.order.expired"
SCHEMA_EXPIREE = RACINE / "docs" / "evenements" / f"{EVENEMENT_COMMANDE_EXPIREE}.json"
ORDERS = "/api/v1/orders"


def _show_cancelled(seance_id: UUID) -> dict[str, str]:
    return {"seance_id": str(seance_id), "evenement_id": str(uuid4())}


def _payment_refunded(commande: Commande, montant: int | None = None) -> dict[str, Any]:
    return {
        "paiement_id": str(uuid4()),
        "commande_id": str(commande.id),
        "seance_id": str(commande.seance_id),
        "montant": montant if montant is not None else commande.montant_total,
    }


def _valider_order_expired(evenement: Any) -> None:
    schema = json.loads(SCHEMA_EXPIREE.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(evenement.model_dump(mode="json"))


# --- ticketing.show.cancelled ---------------------------------------------------------------------


async def test_show_cancelled_expire_les_commandes_en_attente_de_la_seance(depot: Any) -> None:
    s, s2 = uuid4(), uuid4()
    c2 = depot.semer("client-test-2", s, StatutCommande.EN_ATTENTE, lignes=1)
    sans_echeance = depot.semer("client-test-3", s, StatutCommande.EN_ATTENTE, lignes=2)
    depot.commandes[sans_echeance.id] = replace(sans_echeance, expire_le=None)
    c1 = depot.semer("client-test", s, StatutCommande.CONFIRMEE, lignes=2)
    autre = depot.semer("client-test-4", s2, StatutCommande.EN_ATTENTE)

    expirees = await expirer_commandes_de_la_seance(depot, _show_cancelled(s))

    assert expirees == 2
    assert depot.commandes[c2.id].statut is StatutCommande.EXPIREE
    assert depot.commandes[sans_echeance.id].statut is StatutCommande.EXPIREE
    assert depot.commandes[c1.id].statut is StatutCommande.CONFIRMEE
    assert depot.commandes[autre.id].statut is StatutCommande.EN_ATTENTE
    publies = depot.evenements_de(EVENEMENT_COMMANDE_EXPIREE)
    assert len(depot.evenements) == len(publies) == 2
    par_commande = {e.data["commande_id"]: e for e in publies}
    assert set(par_commande) == {str(c2.id), str(sans_echeance.id)}
    for commande in (c2, sans_echeance):
        evenement = par_commande[str(commande.id)]
        _valider_order_expired(evenement)
        assert evenement.data["seance_id"] == str(s)
        assert evenement.data["place_ids"] == [str(ligne.place_id) for ligne in commande.lignes]
        # Aucun remboursement attendu de Commandes : Paiements rembourse lui-même (Q5).
        assert "remboursement_du" not in evenement.data


async def test_show_cancelled_laisse_les_commandes_confirmees_attendre_le_remboursement(
    depot: Any,
) -> None:
    s = uuid4()
    c1 = depot.semer("client-test", s, StatutCommande.CONFIRMEE, lignes=2)
    c3 = depot.semer("revendeur-test", s, StatutCommande.CONFIRMEE, lignes=1)

    expirees = await expirer_commandes_de_la_seance(depot, _show_cancelled(s))

    assert expirees == 0
    assert depot.commandes[c1.id].statut is StatutCommande.CONFIRMEE
    assert depot.commandes[c3.id].statut is StatutCommande.CONFIRMEE
    assert depot.evenements == []


# --- ticketing.payment.refunded -------------------------------------------------------------------


@pytest.mark.parametrize("statut", [StatutCommande.EXPIREE, StatutCommande.REMBOURSEE])
async def test_payment_refunded_ignore_une_commande_expiree_ou_remboursee(
    depot: Any, caplog: pytest.LogCaptureFixture, statut: StatutCommande
) -> None:
    caplog.set_level(logging.INFO)
    commande = depot.semer("client-test", uuid4(), statut, lignes=2)

    nouveau = await enregistrer_remboursement(depot, _payment_refunded(commande))

    assert nouveau is None
    assert depot.commandes[commande.id].statut is statut
    assert depot.evenements == []
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(str(commande.id) in r.getMessage() for r in infos), caplog.text


async def test_payment_refunded_expire_une_commande_encore_en_attente(depot: Any) -> None:
    s = uuid4()
    c2 = depot.semer("client-test-2", s, StatutCommande.EN_ATTENTE, lignes=1)

    nouveau = await enregistrer_remboursement(depot, _payment_refunded(c2))

    assert nouveau is StatutCommande.EXPIREE
    assert depot.commandes[c2.id].statut is StatutCommande.EXPIREE
    publies = depot.evenements_de(EVENEMENT_COMMANDE_EXPIREE)
    assert len(depot.evenements) == len(publies) == 1
    _valider_order_expired(publies[0])
    assert publies[0].data["commande_id"] == str(c2.id)
    assert publies[0].data["place_ids"] == [str(ligne.place_id) for ligne in c2.lignes]


async def test_payment_refunded_d_une_commande_inconnue_est_ignore(
    depot: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    connue = depot.semer("client-test", uuid4(), StatutCommande.CONFIRMEE)
    inconnue = replace(connue, id=uuid4())
    avant = dict(depot.commandes)

    nouveau = await enregistrer_remboursement(depot, _payment_refunded(inconnue))

    assert nouveau is None
    assert depot.commandes == avant
    assert depot.evenements == []
    avertissements = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(str(inconnue.id) in r.getMessage() for r in avertissements), caplog.text
    assert "@" not in caplog.text


async def test_les_commandes_remboursees_ne_comptent_plus_dans_la_limite_de_billets(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], depot: Any
) -> None:
    # Limite par défaut : 10 billets par client et par séance (BIL-008).
    c1 = depot.semer(
        "client-a", seance.id, StatutCommande.CONFIRMEE, email="client.test@exemple.test", lignes=10
    )
    nouveau = await enregistrer_remboursement(depot, _payment_refunded(c1))
    assert nouveau is StatutCommande.REMBOURSEE

    reponse = await client.post(ORDERS, json=seance.corps("A1", "A2"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text
