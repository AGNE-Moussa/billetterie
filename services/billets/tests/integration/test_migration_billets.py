"""E4 (BIL-006, décision Q22) : la migration Alembic crée places, billets et la messagerie.

Base vierge du module (fixture `url_base`, non migrée), migrée par les tests eux-mêmes avec
`services/billets/alembic.ini`. Colonnes : docs/modele-donnees.md (section Billets) ; seule la
longueur de `rang` y est fixée (varchar 10), les autres longueurs ne sont pas vérifiées.
"""

from collections.abc import Callable
from typing import Any

import anyio
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.anyio

REVISION_INITIALE = "0001"
TABLES_DU_TICKET = {"places", "billets", "messages_traites", "outbox"}
VARCHAR = "character varying"
TIMESTAMPTZ = "timestamp with time zone"
COLONNES: dict[str, dict[str, str]] = {
    "places": {
        "id": "uuid",
        "seance_id": "uuid",
        "rang": VARCHAR,
        "numero": "integer",
        "categorie_id": "uuid",
    },
    "billets": {
        "id": "uuid",
        "commande_id": "uuid",
        "client": VARCHAR,
        "seance_id": "uuid",
        "place_id": "uuid",
        "statut": VARCHAR,
        "qr_code": "text",
        "emis_le": TIMESTAMPTZ,
    },
}
CONTRAINTES = {
    ("places", "uq_places_seance_rang_numero", "UNIQUE"),
    ("billets", "uq_billets_place", "UNIQUE"),
    ("billets", "fk_billets_place", "FOREIGN KEY"),
}

Migrer = Callable[..., None]


async def _lire(url: str, requete: str) -> list[Any]:
    moteur = create_async_engine(url, connect_args={"timeout": 30, "command_timeout": 30})
    try:
        async with moteur.connect() as connexion:
            return list((await connexion.execute(sa.text(requete))).mappings())
    finally:
        await moteur.dispose()


async def _tables(url: str) -> set[str]:
    lignes = await _lire(
        url, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    return {ligne["table_name"] for ligne in lignes}


async def _alembic(migration: Migrer, url: str, sens: str, cible: str) -> None:
    # env.py lance sa propre boucle (asyncio.run) : la commande tourne dans un fil.
    await anyio.to_thread.run_sync(lambda: migration(url, cible, sens))


async def test_la_migration_cree_places_billets_et_les_tables_de_messagerie(
    url_base: str, migration: Migrer
) -> None:
    await _alembic(migration, url_base, "upgrade", "head")

    tables = await _tables(url_base)
    assert tables >= TABLES_DU_TICKET, f"tables absentes : {sorted(TABLES_DU_TICKET - tables)}"
    lignes = await _lire(
        url_base,
        "SELECT table_name, column_name, data_type, character_maximum_length"
        " FROM information_schema.columns WHERE table_schema = 'public'"
        " AND table_name IN ('places', 'billets')",
    )
    colonnes: dict[str, dict[str, str]] = {}
    for ligne in lignes:
        colonnes.setdefault(ligne["table_name"], {})[ligne["column_name"]] = ligne["data_type"]
    assert colonnes == COLONNES
    (rang,) = [c for c in lignes if (c["table_name"], c["column_name"]) == ("places", "rang")]
    assert rang["character_maximum_length"] == 10
    contraintes = await _lire(
        url_base,
        "SELECT table_name, constraint_name, constraint_type"
        " FROM information_schema.table_constraints WHERE table_schema = 'public'",
    )
    nommees = {(c["table_name"], c["constraint_name"], c["constraint_type"]) for c in contraintes}
    assert nommees >= CONTRAINTES, f"contraintes absentes : {sorted(CONTRAINTES - nommees)}"


async def test_la_migration_se_defait_et_se_rejoue(url_base: str, migration: Migrer) -> None:
    await _alembic(migration, url_base, "upgrade", "head")

    await _alembic(migration, url_base, "downgrade", REVISION_INITIALE)
    assert not (await _tables(url_base) & TABLES_DU_TICKET)

    await _alembic(migration, url_base, "upgrade", "head")
    tables = await _tables(url_base)
    assert tables >= TABLES_DU_TICKET, f"tables absentes : {sorted(TABLES_DU_TICKET - tables)}"
