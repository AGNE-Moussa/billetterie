"""E2 (BIL-008, décisions Q3 et Q15) : plafond de 10 billets par client et par séance, compté
sous `pg_advisory_xact_lock(client, seance_id)`, sur la vraie base et deux instances.

Hors marqueur `concurrence` : ces cas portent sur le plafond, pas sur la double vente d'une
place ; ils restent dans `make test-integration`.
"""

from collections import Counter
from typing import Any

import pytest

pytestmark = pytest.mark.anyio

# 5 commandes de 3 places distinctes : 15 places de la séance S (A1 à A10, C1 à C5).
LOTS = (
    ("A1", "A2", "A3"),
    ("A4", "A5", "A6"),
    ("A7", "A8", "A9"),
    ("A10", "C1", "C2"),
    ("C3", "C4", "C5"),
)


async def test_des_commandes_simultanees_du_meme_client_ne_depassent_jamais_la_limite(
    plateforme: Any, outils: Any
) -> None:
    async def appel(numero: int) -> Any:
        return await plateforme.commander("A", LOTS[numero], instance=plateforme.instance(numero))

    reponses = await outils.barriere(len(LOTS), appel)

    statuts = Counter(reponse.status_code for reponse in reponses)
    assert set(statuts) <= {201, 409}, [r.text for r in reponses]
    assert 1 <= statuts[201] <= 3, statuts
    assert all(
        r.json()["code"] == "TICKET_LIMIT_EXCEEDED" for r in reponses if r.status_code == 409
    ), [r.text for r in reponses]
    comptees = await plateforme.bases.commandes.compter(
        "SELECT l.place_id FROM lignes_commande l JOIN commandes c ON c.id = l.commande_id"
        " WHERE c.client = 'client-a' AND c.seance_id = :s"
        " AND c.statut IN ('EN_ATTENTE', 'CONFIRMEE')",
        s=plateforme.seance.id,
    )
    assert comptees <= 10, comptees


async def test_deux_clients_simultanes_ne_se_bloquent_pas_sur_le_plafond(
    plateforme: Any, outils: Any
) -> None:
    # Dix places chacun dans la même séance : A1 à A10 pour A, B1 à B10 pour B (rang B ajouté
    # à la séance S pour ce cas, voir le conftest).
    demandes = (
        ("A", [f"A{n}" for n in range(1, 11)]),
        ("B", [f"B{n}" for n in range(1, 11)]),
    )

    async def appel(numero: int) -> Any:
        qui, libelles = demandes[numero]
        return await plateforme.commander(qui, libelles, instance=plateforme.instance(numero))

    reponses = await outils.barriere(2, appel)

    assert [r.status_code for r in reponses] == [201, 201], [r.text for r in reponses]
