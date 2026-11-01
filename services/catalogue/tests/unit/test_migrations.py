"""Migrations de catalogue en mode hors ligne (E1 du plan BIL-004), sans base."""

import io
import re
import secrets
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from commun.outbox import METADONNEES_MESSAGERIE

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
TABLES_METIER = {"evenements", "lieux", "seances", "categories", "rangs"}
TABLES_MESSAGERIE = {"outbox", "messages_traites"}


def _sql_hors_ligne(monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"postgresql+asyncpg://catalogue:{secrets.token_urlsafe(16)}@127.0.0.1:5432/catalogue"
    monkeypatch.setenv("DATABASE_URL", url)
    sortie = io.StringIO()
    command.upgrade(Config(str(ALEMBIC_INI), output_buffer=sortie), "head", sql=True)
    return sortie.getvalue()


def _creation(sql: str, table: str) -> str:
    trouve = re.search(rf"CREATE TABLE\s+{table}\s*\((.*?)\n\);", sql, re.DOTALL | re.IGNORECASE)
    assert trouve is not None, f"CREATE TABLE {table} absent"
    return trouve.group(1)


def test_les_tables_du_service_rejoignent_les_metadonnees_d_alembic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sql = _sql_hors_ligne(monkeypatch)

    tables = set(re.findall(r"CREATE TABLE\s+(\w+)", sql, re.IGNORECASE))

    assert tables - {"alembic_version"} == TABLES_METIER | TABLES_MESSAGERIE
    # Les tables de messagerie sont celles de commun.outbox, colonne pour colonne.
    for nom in TABLES_MESSAGERIE:
        colonnes = set(re.findall(r"^\s+(\w+)\s", _creation(sql, nom), re.MULTILINE))
        attendues = {colonne.name for colonne in METADONNEES_MESSAGERIE.tables[nom].columns}
        assert attendues <= colonnes, (nom, colonnes)
    assert "ix_outbox_en_attente" in sql
