"""Billets d'une séance annulée (CA3 du plan BIL-011), sans base.

`annuler_seance` (domaine.annulation) appelée directement, sur le `data` de
ticketing.show.cancelled, avec le double `DepotBilletsEnMemoire`.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from billets.domaine.annulation import STATUT_ANNULE, annuler_seance
from billets.domaine.emission import STATUT_EMIS

pytestmark = pytest.mark.anyio

ANNULEE_LE = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


async def test_show_cancelled_inscrit_la_seance_et_annule_ses_billets_emis(
    depot_billets: Any,
) -> None:
    s, s2 = uuid4(), uuid4()
    c1, c4 = uuid4(), uuid4()
    a1, a2, place_s2 = uuid4(), uuid4(), uuid4()
    depot_billets.semer_billet(s, a1, c1)
    depot_billets.semer_billet(s, a2, c1)
    depot_billets.semer_billet(s2, place_s2, c4)
    data = {"seance_id": str(s), "evenement_id": str(uuid4())}

    annules = await annuler_seance(depot_billets, data, annulee_le=ANNULEE_LE)

    assert annules == 2
    assert depot_billets.seances_annulees == {s: ANNULEE_LE}
    assert depot_billets.statuts(s) == {a1: STATUT_ANNULE, a2: STATUT_ANNULE}
    assert depot_billets.statuts(s2) == {place_s2: STATUT_EMIS}
    # Verrou exclusif de la séance pris avant tout changement (Q3).
    assert depot_billets.verrous_seance == [s]
