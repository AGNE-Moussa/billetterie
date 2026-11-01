"""E1 (BIL-004) : contraintes de la base du catalogue, par insertions directes.

Base migrée (fixture `database_url`) ; chaque insertion tourne dans sa propre transaction.
Contraintes de docs/modele-donnees.md : CHECK `prix > 0`, CHECK `nombre_places >= 1`, clé
`(seance_id, rang)` de `rangs`, clés étrangères de `seances`.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.anyio


async def _evenement(base: Any) -> UUID:
    identifiant = uuid4()
    await base.executer(
        "INSERT INTO evenements (id, nom, description, cree_le)"
        " VALUES (:id, 'Concert de test', 'Description synthétique', now())",
        id=identifiant,
    )
    return identifiant


async def _lieu(base: Any) -> UUID:
    identifiant = uuid4()
    await base.executer(
        "INSERT INTO lieux (id, nom, adresse, ville, cree_le)"
        " VALUES (:id, 'Salle de test', '1 rue de l''Exemple', 'Villetest', now())",
        id=identifiant,
    )
    return identifiant


async def _seance(base: Any, evenement_id: UUID, lieu_id: UUID) -> UUID:
    identifiant = uuid4()
    await base.executer(
        "INSERT INTO seances (id, evenement_id, lieu_id, debut, annulee, cree_le)"
        " VALUES (:id, :evenement_id, :lieu_id, :debut, false, now())",
        id=identifiant,
        evenement_id=evenement_id,
        lieu_id=lieu_id,
        debut=datetime.now(UTC) + timedelta(days=30),
    )
    return identifiant


async def _categorie(
    base: Any, seance_id: UUID, nom: str = "Fosse", prix: int = 4500, position: int = 0
) -> UUID:
    identifiant = uuid4()
    await base.executer(
        "INSERT INTO categories (id, seance_id, nom, prix, position)"
        " VALUES (:id, :seance_id, :nom, :prix, :position)",
        id=identifiant,
        seance_id=seance_id,
        nom=nom,
        prix=prix,
        position=position,
    )
    return identifiant


async def _rang(
    base: Any,
    seance_id: UUID,
    categorie_id: UUID,
    rang: str = "A",
    nombre_places: int = 10,
    position: int = 0,
) -> None:
    await base.executer(
        "INSERT INTO rangs (seance_id, rang, categorie_id, nombre_places, position)"
        " VALUES (:seance_id, :rang, :categorie_id, :nombre_places, :position)",
        seance_id=seance_id,
        rang=rang,
        categorie_id=categorie_id,
        nombre_places=nombre_places,
        position=position,
    )


def _contrainte_violee(erreur: IntegrityError) -> str:
    """Nom de la contrainte violée, lu dans le message PostgreSQL (`... constraint "<nom>"`).

    Un NOT NULL ne nomme aucune contrainte : il fait échouer l'assertion au lieu de passer.
    """
    message = str(erreur.orig)
    marqueur = 'constraint "'
    debut = message.find(marqueur)
    assert debut != -1, f"Aucune contrainte nommée dans l'erreur : {message}"
    debut += len(marqueur)
    return message[debut : message.index('"', debut)]


async def _seance_complete(base: Any) -> UUID:
    return await _seance(base, await _evenement(base), await _lieu(base))


@pytest.mark.parametrize("prix", [0, -100])
async def test_la_base_refuse_un_prix_nul_ou_negatif(base: Any, prix: int) -> None:
    await base.exiger_tables()
    seance_id = await _seance_complete(base)

    with pytest.raises(IntegrityError) as erreur:
        await _categorie(base, seance_id, prix=prix)

    assert _contrainte_violee(erreur.value) == "ck_categories_prix_positif"

    assert await base.compter("categories") == 0


async def test_la_base_refuse_un_rang_sans_place(base: Any) -> None:
    await base.exiger_tables()
    seance_id = await _seance_complete(base)
    categorie_id = await _categorie(base, seance_id)

    with pytest.raises(IntegrityError) as erreur:
        await _rang(base, seance_id, categorie_id, nombre_places=0)

    assert _contrainte_violee(erreur.value) == "ck_rangs_nombre_places_minimum"

    assert await base.compter("rangs") == 0


async def test_la_base_refuse_un_meme_rang_deux_fois_dans_une_seance(base: Any) -> None:
    await base.exiger_tables()
    seance_id = await _seance_complete(base)
    fosse = await _categorie(base, seance_id, nom="Fosse")
    balcon = await _categorie(base, seance_id, nom="Balcon", position=1)
    await _rang(base, seance_id, fosse, rang="A")

    with pytest.raises(IntegrityError) as erreur:
        await _rang(base, seance_id, balcon, rang="A")

    assert _contrainte_violee(erreur.value) == "pk_rangs"

    assert await base.compter("rangs") == 1


async def test_la_base_refuse_une_seance_sans_evenement_ou_sans_lieu_existant(base: Any) -> None:
    await base.exiger_tables()
    evenement_id = await _evenement(base)
    lieu_id = await _lieu(base)

    with pytest.raises(IntegrityError) as sans_evenement:
        await _seance(base, uuid4(), lieu_id)
    with pytest.raises(IntegrityError) as sans_lieu:
        await _seance(base, evenement_id, uuid4())

    assert _contrainte_violee(sans_evenement.value) == "fk_seances_evenement_id"
    assert _contrainte_violee(sans_lieu.value) == "fk_seances_lieu_id"

    assert await base.compter("seances") == 0
