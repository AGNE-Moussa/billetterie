"""E3 (BIL-006, décisions Q7 et Q14) : disponibilité des places sur vraie base et vrai Redis.

Une place est indisponible si elle porte un verrou Redis ou un billet en base.
"""

import asyncio
import uuid
from collections import Counter
from typing import Any

import pytest

pytestmark = pytest.mark.anyio

ATTENTE_EXPIRATION = 2.5
PLACES_VERROUILLEES = 20


async def test_la_disponibilite_reflete_le_verrou_redis_et_le_billet_en_base(
    plateforme_courte: Any, seance: Any, base: Any, outils: Any
) -> None:
    a1, a2, a3 = (str(seance.places[libelle]) for libelle in ("A1", "A2", "A3"))
    outils.exiger_statut(
        await plateforme_courte.verrouiller(seance.id, a1, uuid.uuid4()), 200, "verrou de A1"
    )
    await base.inserer_billet(seance.id, seance.places["A2"])

    pendant = await plateforme_courte.disponibilites(seance.id)
    assert (pendant[a1], pendant[a2], pendant[a3]) == (False, False, True), pendant

    await asyncio.sleep(ATTENTE_EXPIRATION)
    apres = await plateforme_courte.disponibilites(seance.id)
    assert (apres[a1], apres[a2], apres[a3]) == (True, False, True), apres


async def test_la_disponibilite_lue_pendant_des_verrouillages_simultanes_reste_coherente(
    plateforme: Any, seance: Any, outils: Any
) -> None:
    libelles = seance.ordre()[-PLACES_VERROUILLEES:]
    reponses = await outils.borne(
        f"{PLACES_VERROUILLEES} PUT simultanés",
        asyncio.gather(
            *(
                plateforme.verrouiller(
                    seance.id,
                    seance.places[libelle],
                    uuid.uuid4(),
                    client=plateforme.instance(numero),
                )
                for numero, libelle in enumerate(libelles)
            )
        ),
    )
    statuts = Counter(reponse.status_code for reponse in reponses)
    assert statuts == {200: PLACES_VERROUILLEES}, statuts

    disponibilites = await plateforme.disponibilites(seance.id)

    assert len(disponibilites) == outils.nombre_places
    indisponibles = {place for place, libre in disponibilites.items() if not libre}
    assert indisponibles == {str(seance.places[libelle]) for libelle in libelles}
