"""CA1 et E4 (BIL-006) : contraintes uniques de la base, sans passer par l'application.

Les insertions simultanées pour la même place sont prouvées à N = 50 × 10 par
test_concurrence_ventes.py (BIL-007, décision Q7).

`uq_billets_place` garantit qu'une place n'est vendue qu'une fois même si le verrou Redis
échoue ; `uq_places_seance_rang_numero` interdit deux places identiques dans une séance.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.anyio

CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}
INSERER_PLACE = sa.text(
    "INSERT INTO places (id, seance_id, rang, numero, categorie_id)"
    " VALUES (:id, :seance_id, :rang, :numero, :categorie_id)"
)
INSERER_BILLET = sa.text(
    "INSERT INTO billets (id, commande_id, client, seance_id, place_id, statut, qr_code, emis_le)"
    " VALUES (:id, :commande_id, :client, :seance_id, :place_id, 'EMIS', :qr_code, :emis_le)"
)


def _place(seance_id: uuid.UUID, rang: str = "A", numero: int = 1) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "seance_id": seance_id,
        "rang": rang,
        "numero": numero,
        "categorie_id": uuid.uuid4(),
    }


async def test_deux_places_de_meme_rang_et_numero_dans_une_seance_sont_refusees_par_la_base(
    database_url: str, base: Any
) -> None:
    await base.exiger_tables("places")
    seance_id = uuid.uuid4()
    moteur = create_async_engine(database_url, connect_args=CONNEXION_BORNEE)
    try:
        async with moteur.begin() as connexion:
            await connexion.execute(INSERER_PLACE, _place(seance_id))
        with pytest.raises(IntegrityError) as erreur:
            async with moteur.begin() as connexion:
                await connexion.execute(INSERER_PLACE, _place(seance_id))
    finally:
        await moteur.dispose()

    assert "uq_places_seance_rang_numero" in str(erreur.value)
    assert await base.compter("places") == 1


def _billet(seance_id: uuid.UUID, place_id: uuid.UUID) -> dict[str, Any]:
    billet = uuid.uuid4()
    return {
        "id": billet,
        "commande_id": uuid.uuid4(),
        "client": "client.test@exemple.test",
        "seance_id": seance_id,
        "place_id": place_id,
        "qr_code": f"qr-de-test-{billet}",
        "emis_le": datetime.now(UTC),
    }


async def test_un_billet_dont_la_place_n_appartient_pas_a_sa_seance_est_refuse_par_la_base(
    database_url: str, base: Any, seance: Any
) -> None:
    """Review BIL-006, point 3 : la séance du billet doit être celle de sa place."""
    autre_seance = uuid.uuid4()
    place_autre_seance = _place(autre_seance)
    place_de_la_seance = seance.places["A1"]
    moteur = create_async_engine(database_url, connect_args=CONNEXION_BORNEE)
    try:
        async with moteur.begin() as connexion:
            await connexion.execute(INSERER_PLACE, place_autre_seance)

        # Place d'une autre séance, présentée sous la séance commune.
        with pytest.raises(IntegrityError) as erreur:
            async with moteur.begin() as connexion:
                await connexion.execute(
                    INSERER_BILLET, _billet(seance.id, place_autre_seance["id"])
                )
        assert "fk_billets_place" in str(erreur.value)

        # Un billet valide, puis la même place_id sous une autre séance : refusé.
        async with moteur.begin() as connexion:
            await connexion.execute(INSERER_BILLET, _billet(seance.id, place_de_la_seance))
        with pytest.raises(IntegrityError):
            async with moteur.begin() as connexion:
                await connexion.execute(INSERER_BILLET, _billet(autre_seance, place_de_la_seance))
    finally:
        await moteur.dispose()

    assert await base.compter("billets") == 1
    assert await base.compter("billets", "place_id = :place", place=place_de_la_seance) == 1


async def test_la_meme_place_dans_deux_seances_differentes_est_acceptee(
    database_url: str, base: Any
) -> None:
    await base.exiger_tables("places")
    moteur = create_async_engine(database_url, connect_args=CONNEXION_BORNEE)
    try:
        async with moteur.begin() as connexion:
            await connexion.execute(INSERER_PLACE, _place(uuid.uuid4()))
            await connexion.execute(INSERER_PLACE, _place(uuid.uuid4()))
    finally:
        await moteur.dispose()

    assert await base.compter("places") == 2
