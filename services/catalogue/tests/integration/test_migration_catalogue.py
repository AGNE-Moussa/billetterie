"""E1 (BIL-004) : la migration Alembic crée les tables du modèle et de la messagerie.

Base vierge du module (fixture `url_base`, non migrée), migrée par les tests eux-mêmes avec
`services/catalogue/alembic.ini`. Colonnes et types : docs/modele-donnees.md (Catalogue) et
commun.outbox (outbox, messages_traites).
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.anyio

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
REVISION_INITIALE = "0001"
TABLES_DU_TICKET = {
    "evenements",
    "lieux",
    "seances",
    "categories",
    "rangs",
    "outbox",
    "messages_traites",
}
VARCHAR = "character varying"
TIMESTAMPTZ = "timestamp with time zone"
# (type, longueur maximale) de chaque colonne, docs/modele-donnees.md.
COLONNES: dict[str, dict[str, tuple[str, int | None]]] = {
    "evenements": {
        "id": ("uuid", None),
        "nom": (VARCHAR, 200),
        "description": (VARCHAR, 5000),
        "cree_le": (TIMESTAMPTZ, None),
    },
    "lieux": {
        "id": ("uuid", None),
        "nom": (VARCHAR, 200),
        "adresse": (VARCHAR, 300),
        "ville": (VARCHAR, 100),
        "cree_le": (TIMESTAMPTZ, None),
    },
    "seances": {
        "id": ("uuid", None),
        "evenement_id": ("uuid", None),
        "lieu_id": ("uuid", None),
        "debut": (TIMESTAMPTZ, None),
        "annulee": ("boolean", None),
        "cree_le": (TIMESTAMPTZ, None),
    },
    "categories": {
        "id": ("uuid", None),
        "seance_id": ("uuid", None),
        "nom": (VARCHAR, 100),
        "prix": ("integer", None),
        # Décision I1 : position dans la séance, à partir de 0.
        "position": ("integer", None),
    },
    "rangs": {
        "seance_id": ("uuid", None),
        "rang": (VARCHAR, 10),
        "categorie_id": ("uuid", None),
        "nombre_places": ("integer", None),
        # Décision I1 : position dans la catégorie, à partir de 0.
        "position": ("integer", None),
    },
}
# Colonnes qui portent l'ordre de la requête (décision I1) : obligatoires.
COLONNES_DE_POSITION = (("categories", "position"), ("rangs", "position"))

Migrer = Callable[..., None]


async def _lire(url: str, requete: str) -> list[Any]:
    moteur = create_async_engine(url, connect_args={"timeout": 30, "command_timeout": 30})
    try:
        async with moteur.connect() as connexion:
            return list((await connexion.execute(sa.text(requete))).mappings())
    finally:
        await moteur.dispose()


async def _versions(url: str) -> list[str]:
    lignes = await _lire(url, "SELECT version_num FROM alembic_version")
    return [ligne["version_num"] for ligne in lignes]


async def _tables(url: str) -> set[str]:
    lignes = await _lire(
        url, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    return {ligne["table_name"] for ligne in lignes}


async def _colonnes(url: str) -> dict[str, dict[str, tuple[str, int | None]]]:
    lignes = await _lire(
        url,
        "SELECT table_name, column_name, data_type, character_maximum_length"
        " FROM information_schema.columns WHERE table_schema = 'public'",
    )
    colonnes: dict[str, dict[str, tuple[str, int | None]]] = {}
    for ligne in lignes:
        colonnes.setdefault(ligne["table_name"], {})[ligne["column_name"]] = (
            ligne["data_type"],
            ligne["character_maximum_length"],
        )
    return colonnes


async def _nullables(url: str) -> dict[tuple[str, str], str]:
    lignes = await _lire(
        url,
        "SELECT table_name, column_name, is_nullable"
        " FROM information_schema.columns WHERE table_schema = 'public'",
    )
    return {(ligne["table_name"], ligne["column_name"]): ligne["is_nullable"] for ligne in lignes}


async def _alembic(migration: Migrer, url: str, sens: str, cible: str) -> None:
    # env.py lance sa propre boucle (asyncio.run) : la commande tourne dans un fil.
    await anyio.to_thread.run_sync(lambda: migration(url, cible, sens))


async def test_la_migration_cree_les_tables_du_modele_et_de_la_messagerie(
    url_base: str, migration: Migrer
) -> None:
    await _alembic(migration, url_base, "upgrade", "head")

    tables = await _tables(url_base)
    assert tables >= TABLES_DU_TICKET, f"tables absentes : {sorted(TABLES_DU_TICKET - tables)}"
    colonnes = await _colonnes(url_base)
    for table, attendues in COLONNES.items():
        assert colonnes[table] == attendues, table
    nullables = await _nullables(url_base)
    for colonne in COLONNES_DE_POSITION:
        assert nullables.get(colonne) == "NO", f"{colonne} doit exister et être NOT NULL"
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    tetes = script.get_heads()
    assert len(tetes) == 1, tetes
    assert tetes[0] != REVISION_INITIALE, "aucune révision après 0001"
    revision = script.get_revision(tetes[0])
    assert revision is not None and revision.down_revision == REVISION_INITIALE
    assert await _versions(url_base) == [tetes[0]]


async def test_la_migration_se_rejoue_sans_effet(url_base: str, migration: Migrer) -> None:
    await _alembic(migration, url_base, "upgrade", "head")
    avant = await _versions(url_base)

    await _alembic(migration, url_base, "upgrade", "head")

    assert await _versions(url_base) == avant
    assert avant != [REVISION_INITIALE], "la base est restée à 0001 : aucune migration du ticket"


async def test_la_migration_se_defait_puis_se_rejoue(url_base: str, migration: Migrer) -> None:
    await _alembic(migration, url_base, "upgrade", "head")

    await _alembic(migration, url_base, "downgrade", REVISION_INITIALE)
    assert await _versions(url_base) == [REVISION_INITIALE]
    assert not (await _tables(url_base) & TABLES_DU_TICKET)

    await _alembic(migration, url_base, "upgrade", "head")
    tables = await _tables(url_base)
    assert tables >= TABLES_DU_TICKET, f"tables absentes : {sorted(TABLES_DU_TICKET - tables)}"
