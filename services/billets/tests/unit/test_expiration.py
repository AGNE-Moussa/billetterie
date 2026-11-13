"""Libération des places d'une commande expirée (plan BIL-010, CA1 « Billets »), sans Redis.

`liberer_places_expirees` appelée directement sur le magasin `VerrousEnMemoire` (conftest) et
le `data` de ticketing.order.expired d'une commande `A` (docs/evenements/).
"""

from typing import Any
from uuid import UUID, uuid4

import pytest

from billets.domaine.expiration import DonneesExpirationInvalides, liberer_places_expirees

pytestmark = pytest.mark.anyio

DUREE = 600


def _data(commande_id: UUID, seance_id: UUID, *place_ids: UUID) -> dict[str, Any]:
    return {
        "commande_id": str(commande_id),
        "seance_id": str(seance_id),
        "place_ids": [str(p) for p in place_ids],
    }


async def test_l_expiration_libere_les_verrous_detenus_par_la_commande(verrous: Any) -> None:
    seance_id, commande_a, place_1, place_2 = uuid4(), uuid4(), uuid4(), uuid4()
    verrous.semer(seance_id, place_1, commande_a, DUREE)
    verrous.semer(seance_id, place_2, commande_a, DUREE)

    await liberer_places_expirees(verrous, _data(commande_a, seance_id, place_1, place_2))

    assert verrous.detenteur(seance_id, place_1) is None
    assert verrous.detenteur(seance_id, place_2) is None


async def test_l_expiration_ne_supprime_pas_un_verrou_repris_par_une_autre_commande(
    verrous: Any,
) -> None:
    seance_id, commande_a, commande_b = uuid4(), uuid4(), uuid4()
    place_1, place_2 = uuid4(), uuid4()
    verrous.semer(seance_id, place_1, commande_a, DUREE)
    verrous.semer(seance_id, place_2, commande_b, DUREE)
    expiration_b = verrous.expiration(seance_id, place_2)

    await liberer_places_expirees(verrous, _data(commande_a, seance_id, place_1, place_2))

    assert verrous.detenteur(seance_id, place_1) is None
    assert verrous.detenteur(seance_id, place_2) == str(commande_b)
    assert verrous.expiration(seance_id, place_2) == expiration_b


async def test_l_expiration_d_une_place_sans_verrou_ne_fait_rien(verrous: Any) -> None:
    seance_id, commande_a, place_1 = uuid4(), uuid4(), uuid4()

    await liberer_places_expirees(verrous, _data(commande_a, seance_id, place_1))

    assert verrous.cles() == {}
    # Le magasin a bien été interrogé (comparer puis supprimer), sans rien créer.
    assert verrous.appels >= 1


async def test_l_expiration_ignore_le_champ_remboursement_du(verrous: Any) -> None:
    seance_id, commande_a, commande_b = uuid4(), uuid4(), uuid4()
    place_1, place_2, place_autre = uuid4(), uuid4(), uuid4()
    verrous.semer(seance_id, place_1, commande_a, DUREE)
    verrous.semer(seance_id, place_2, commande_a, DUREE)
    verrous.semer(seance_id, place_autre, commande_b, DUREE)
    data = {**_data(commande_a, seance_id, place_1, place_2), "remboursement_du": True}

    await liberer_places_expirees(verrous, data)

    assert verrous.cles() == {f"place:{seance_id}:{place_autre}": str(commande_b)}


@pytest.mark.parametrize(
    "corruption",
    [{"place_ids": []}, {"commande_id": "pas-un-uuid"}],
    ids=["place_ids_vide", "commande_id_non_uuid"],
)
async def test_des_donnees_d_expiration_invalides_levent_une_exception(
    verrous: Any, corruption: dict[str, Any]
) -> None:
    seance_id, commande_a, place_1 = uuid4(), uuid4(), uuid4()
    verrous.semer(seance_id, place_1, commande_a, DUREE)
    data = {**_data(commande_a, seance_id, place_1), **corruption}

    with pytest.raises(DonneesExpirationInvalides):
        await liberer_places_expirees(verrous, data)

    # Rien n'est libéré sur des données inexploitables.
    assert verrous.detenteur(seance_id, place_1) == str(commande_a)
