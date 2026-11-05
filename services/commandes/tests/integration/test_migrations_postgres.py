"""E9 (BIL-008) : migrations de Commandes (et aller-retour de celles de Paiements) sur une base
neuve du conteneur du module, par `alembic upgrade head` avec le alembic.ini du service.
"""

import secrets
from collections.abc import Callable
from typing import Any

import anyio
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.anyio

CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}
MOTS_DE_CARTE = ("carte", "card", "pan", "cvv")


async def _lignes(url: str, requete: str) -> list[dict[str, Any]]:
    moteur = create_async_engine(url, poolclass=NullPool, connect_args=CONNEXION_BORNEE)
    try:
        async with moteur.connect() as connexion:
            return [dict(ligne) for ligne in (await connexion.execute(sa.text(requete))).mappings()]
    finally:
        await moteur.dispose()


async def _base_neuve(serveur: Any) -> str:
    """Base neuve, non migrée (création et migrations bloquantes : dans un fil)."""
    nom = f"migration_{secrets.token_hex(4)}"
    return await anyio.to_thread.run_sync(lambda: serveur.creer_base(nom))


async def _migrer(migration: Callable[..., None], *arguments: str) -> None:
    await anyio.to_thread.run_sync(lambda: migration(*arguments))


async def test_les_migrations_de_commandes_creent_le_modele(
    serveur: Any, migration: Callable[..., None]
) -> None:
    url = await _base_neuve(serveur)

    await _migrer(migration, "commandes", url)

    tables = {
        ligne["table_name"]
        for ligne in await _lignes(
            url, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
    }
    assert {"commandes", "lignes_commande", "outbox", "messages_traites"} <= tables, tables
    uniques = await _lignes(
        url,
        "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint"
        " WHERE conrelid = 'commandes'::regclass AND contype = 'u'",
    )
    assert any(u["def"] == "UNIQUE (client, cle_idempotence)" for u in uniques), uniques
    index = await _lignes(url, "SELECT indexdef FROM pg_indexes WHERE tablename = 'commandes'")
    assert any("(client, seance_id)" in i["indexdef"] for i in index), index
    colonnes = await _lignes(
        url,
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = 'public'",
    )
    assert not [
        c
        for c in colonnes
        if any(mot in c["column_name"].lower().split("_") for mot in MOTS_DE_CARTE)
    ], colonnes


@pytest.mark.parametrize("service", ["commandes", "paiements"])
async def test_les_migrations_se_defont_et_se_rejouent(
    service: str, serveur: Any, migration: Callable[..., None]
) -> None:
    url = await _base_neuve(serveur)

    await _migrer(migration, service, url)
    await _migrer(migration, service, url, "base", "downgrade")
    apres_retour = await _lignes(
        url, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    await _migrer(migration, service, url)

    assert {t["table_name"] for t in apres_retour} <= {"alembic_version"}, apres_retour
    versions = await _lignes(url, "SELECT version_num FROM alembic_version")
    assert [v["version_num"] for v in versions] == ["0003"], versions
