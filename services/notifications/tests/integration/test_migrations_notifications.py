"""BIL-009, E5 (décision Q8, H6) : les migrations de notifications créent la messagerie,
`destinataires_commande` et `envois` (plan docs/test-plans/BIL-009.md).

Base vierge du module (`url_base`), migrée par les tests eux-mêmes avec
`services/notifications/alembic.ini` ; colonnes et contraintes : docs/modele-donnees.md (section
Notifications), sans clé étrangère `destinataires_commande.seance_id` (H6).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import anyio
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.anyio

REVISION_INITIALE = "0001"
TABLES_DU_TICKET = {"outbox", "messages_traites", "destinataires_commande", "envois"}
CONTRAINTES = {
    ("destinataires_commande", "pk_destinataires_commande", "PRIMARY KEY"),
    ("envois", "uq_envois_evenement_commande", "UNIQUE"),
    ("envois", "fk_envois_commande", "FOREIGN KEY"),
}
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}

Migrer = Callable[..., None]


async def _lire(url: str, requete: str, **parametres: Any) -> list[Any]:
    moteur = create_async_engine(url, connect_args=CONNEXION_BORNEE)
    try:
        async with moteur.begin() as connexion:
            resultat = await connexion.execute(sa.text(requete), parametres)
            return list(resultat.mappings()) if resultat.returns_rows else []
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


async def test_les_migrations_de_notifications_creent_le_modele(
    url_base: str, migration: Migrer
) -> None:
    await _alembic(migration, url_base, "upgrade", "head")

    tables = await _tables(url_base)
    assert tables >= TABLES_DU_TICKET, f"tables absentes : {sorted(TABLES_DU_TICKET - tables)}"
    contraintes = await _lire(
        url_base,
        "SELECT table_name, constraint_name, constraint_type"
        " FROM information_schema.table_constraints WHERE table_schema = 'public'",
    )
    nommees = {(c["table_name"], c["constraint_name"], c["constraint_type"]) for c in contraintes}
    assert nommees >= CONTRAINTES, f"contraintes absentes : {sorted(CONTRAINTES - nommees)}"
    cles = await _lire(
        url_base,
        "SELECT column_name FROM information_schema.key_column_usage"
        " WHERE table_schema = 'public' AND constraint_name = 'pk_destinataires_commande'",
    )
    assert [c["column_name"] for c in cles] == ["commande_id"]
    colonnes = await _lire(
        url_base,
        "SELECT column_name, is_nullable FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name = 'destinataires_commande'",
    )
    nullables = {c["column_name"]: c["is_nullable"] for c in colonnes}
    assert nullables.get("email") == "YES", nullables
    etrangeres = {
        c["constraint_name"]
        for c in contraintes
        if c["table_name"] == "destinataires_commande" and c["constraint_type"] == "FOREIGN KEY"
    }
    assert etrangeres == set(), f"clé étrangère inattendue (H6) : {etrangeres}"


async def test_la_base_refuse_deux_envois_du_meme_evenement_pour_la_meme_commande(
    database_url: str,
) -> None:
    commande_id, evenement_id = uuid.uuid4(), uuid.uuid4()
    await _lire(
        database_url,
        "INSERT INTO destinataires_commande (commande_id, email, seance_id)"
        " VALUES (:commande_id, :email, :seance_id)",
        commande_id=commande_id,
        email="client.test@exemple.test",
        seance_id=uuid.uuid4(),
    )
    envoi = (
        "INSERT INTO envois (id, evenement_id, type_evenement, commande_id, destinataire,"
        " envoye_le) VALUES (:id, :evenement_id, :type_evenement, :commande_id,"
        " :destinataire, :envoye_le)"
    )
    valeurs: dict[str, Any] = {
        "evenement_id": evenement_id,
        "type_evenement": "ticketing.ticket.issued",
        "commande_id": commande_id,
        "destinataire": "client.test@exemple.test",
        "envoye_le": datetime.now(UTC),
    }
    await _lire(database_url, envoi, id=uuid.uuid4(), **valeurs)

    with pytest.raises(IntegrityError) as refus:
        await _lire(database_url, envoi, id=uuid.uuid4(), **valeurs)

    assert "uq_envois_evenement_commande" in str(refus.value)


async def test_les_migrations_se_defont_et_se_rejouent(url_base: str, migration: Migrer) -> None:
    await _alembic(migration, url_base, "upgrade", "head")

    await _alembic(migration, url_base, "downgrade", REVISION_INITIALE)
    assert not (await _tables(url_base) & TABLES_DU_TICKET)

    await _alembic(migration, url_base, "upgrade", "head")
    tables = await _tables(url_base)
    assert tables >= TABLES_DU_TICKET, f"tables absentes : {sorted(TABLES_DU_TICKET - tables)}"
