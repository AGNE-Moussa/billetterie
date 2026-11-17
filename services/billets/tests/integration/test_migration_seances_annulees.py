"""BIL-009, E5 (décision Q3) : la migration 0004 crée `seances_annulees`, vide (plan
docs/test-plans/BIL-009.md).

Base vierge du module (`url_base`), migrée par les tests eux-mêmes avec
`services/billets/alembic.ini`.
"""

from collections.abc import Callable
from typing import Any

import anyio
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.anyio

REVISION_PRECEDENTE = "0003"

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


async def test_les_migrations_de_billets_creent_seances_annulees(
    url_base: str, migration: Migrer
) -> None:
    await _alembic(migration, url_base, "upgrade", "head")

    assert "seances_annulees" in await _tables(url_base)
    assert await _lire(url_base, "SELECT * FROM seances_annulees") == []
    contraintes = await _lire(
        url_base,
        "SELECT constraint_name, constraint_type FROM information_schema.table_constraints"
        " WHERE table_schema = 'public' AND table_name = 'seances_annulees'",
    )
    assert ("pk_seances_annulees", "PRIMARY KEY") in {
        (c["constraint_name"], c["constraint_type"]) for c in contraintes
    }


async def test_les_migrations_se_defont_et_se_rejouent(url_base: str, migration: Migrer) -> None:
    await _alembic(migration, url_base, "upgrade", "head")

    await _alembic(migration, url_base, "downgrade", REVISION_PRECEDENTE)
    assert "seances_annulees" not in await _tables(url_base)

    await _alembic(migration, url_base, "upgrade", "head")
    assert "seances_annulees" in await _tables(url_base)
