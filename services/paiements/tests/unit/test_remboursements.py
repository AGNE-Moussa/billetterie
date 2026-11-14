"""Remboursements d'une séance annulée (CA1, Paiements, du plan BIL-011), sans base.

`rembourser_seance` (domaine.remboursements) appelée directement sur le `data` de
ticketing.show.cancelled, avec le double `DepotEnMemoire` (port `DepotRemboursements`).
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import jsonschema
import pytest

from paiements.domaine.paiements import StatutPaiement
from paiements.domaine.remboursements import EVENEMENT_PAIEMENT_REMBOURSE, rembourser_seance

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[4]
SCHEMA = RACINE / "docs" / "evenements" / f"{EVENEMENT_PAIEMENT_REMBOURSE}.json"
ANNULEE_LE = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def _show_cancelled(seance_id: Any) -> dict[str, str]:
    return {"seance_id": str(seance_id), "evenement_id": str(uuid4())}


async def test_show_cancelled_rembourse_chaque_paiement_accepte_de_la_seance(depot: Any) -> None:
    s, s2 = uuid4(), uuid4()
    p1 = depot.semer(s, montant=9000)
    p3 = depot.semer(s, montant=4500)
    refuse = depot.semer(s, StatutPaiement.REFUSE)
    p4 = depot.semer(s2)

    rembourses = await rembourser_seance(depot, _show_cancelled(s), annulee_le=ANNULEE_LE)

    assert {p.id for p in rembourses} == {p1.id, p3.id}
    assert depot.statut(p1) is StatutPaiement.REMBOURSE
    assert depot.statut(p3) is StatutPaiement.REMBOURSE
    assert depot.statut(refuse) is StatutPaiement.REFUSE
    assert depot.statut(p4) is StatutPaiement.ACCEPTE
    assert s in depot.seances_annulees
    assert s2 not in depot.seances_annulees
    publies = [e for e in depot.evenements if e.type == EVENEMENT_PAIEMENT_REMBOURSE]
    assert sorted(e.data["paiement_id"] for e in publies) == sorted([str(p1.id), str(p3.id)])
    assert len(depot.evenements) == 2
    # Verrou exclusif de la séance pris (Q2).
    assert depot.verrous_seance == [s]


async def test_le_remboursement_publie_payment_refunded_conforme_au_schema(depot: Any) -> None:
    s = uuid4()
    c1 = uuid4()
    p1 = depot.semer(s, montant=9000, commande_id=c1)

    await rembourser_seance(depot, _show_cancelled(s), annulee_le=ANNULEE_LE)

    assert len(depot.evenements) == 1
    evenement = depot.evenements[0]
    assert evenement.type == EVENEMENT_PAIEMENT_REMBOURSE
    assert evenement.data == {
        "paiement_id": str(p1.id),
        "commande_id": str(c1),
        "seance_id": str(s),
        "montant": 9000,
    }
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(evenement.model_dump(mode="json"))
