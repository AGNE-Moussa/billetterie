"""Clé d'idempotence et pool de connexions (review BIL-008, point 4).

La connexion de la clé n'est pas tenue pendant les appels HTTP (ou l'attente du pool est bornée
par `delai_base`) : plus de requêtes simultanées avec clé que `pool_size + max_overflow` (5 + 10
par défaut) sur une seule instance se terminent toutes, dans un délai borné, sans 503.
"""

import time
from collections import Counter
from typing import Any

import pytest

pytestmark = pytest.mark.anyio

REQUETES = 20
# Bien en deçà du pool_timeout par défaut (30 s) d'un pool affamé.
DELAI_MAX = 20.0
LIBELLES = [f"A{n}" for n in range(1, 11)] + [f"B{n}" for n in range(1, 11)]


def _client(numero: int) -> dict[str, Any]:
    return {
        "sujet": f"client-pool-{numero:02d}",
        "roles": ["customer"],
        "scopes": ["orders:read", "orders:write"],
        "email": f"client.pool.{numero:02d}@exemple.test",
    }


async def test_vingt_commandes_simultanees_avec_cle_sur_une_instance_se_terminent_sans_503(
    plateforme: Any, outils: Any
) -> None:
    async def appel(numero: int) -> Any:
        return await plateforme.commander(
            _client(numero),
            [LIBELLES[numero]],
            cle=f"cle-pool-{numero:02d}",
            instance=plateforme.commandes_1,
        )

    debut = time.monotonic()
    reponses = await outils.barriere(REQUETES, appel)
    duree = time.monotonic() - debut

    statuts = Counter(reponse.status_code for reponse in reponses)
    echecs = [reponse.text for reponse in reponses if reponse.status_code != 201]
    assert statuts == {201: REQUETES}, (statuts, echecs[:3])
    assert duree < DELAI_MAX, f"{REQUETES} commandes en {duree:.1f} s"
    confirmees = await plateforme.bases.commandes.compter(
        "SELECT id FROM commandes WHERE statut = 'CONFIRMEE'"
    )
    assert confirmees == REQUETES
