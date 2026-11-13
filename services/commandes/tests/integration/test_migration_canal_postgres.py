"""Migration 0005 de Commandes (BIL-012, décision Q3, question 3 du plan) : colonne `canal`
non nulle, bornée par `ck_commandes_canal`, remplie pour les commandes existantes
(`PARTENAIRE` si `email IS NULL`, `DIRECT` sinon). Base neuve du conteneur du module, vraies
migrations Alembic.
"""

import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.anyio

CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}
CONTRAINTE = "ck_commandes_canal"


async def _executer(url: str, requete: str, **parametres: Any) -> list[dict[str, Any]]:
    moteur = create_async_engine(url, poolclass=NullPool, connect_args=CONNEXION_BORNEE)
    try:
        async with moteur.begin() as connexion:
            resultat = await connexion.execute(sa.text(requete), parametres)
            return [dict(ligne) for ligne in resultat.mappings()] if resultat.returns_rows else []
    finally:
        await moteur.dispose()


async def _base_neuve(serveur: Any) -> str:
    nom = f"canal_{secrets.token_hex(4)}"
    return await anyio.to_thread.run_sync(lambda: serveur.creer_base(nom))


async def _migrer(migration: Callable[..., None], *arguments: str) -> None:
    await anyio.to_thread.run_sync(lambda: migration(*arguments))


async def _colonne_canal(url: str) -> list[dict[str, Any]]:
    return await _executer(
        url,
        "SELECT is_nullable, column_default FROM information_schema.columns"
        " WHERE table_name = 'commandes' AND column_name = 'canal'",
    )


async def _contrainte(url: str) -> list[dict[str, Any]]:
    return await _executer(
        url,
        "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint"
        " WHERE conrelid = 'commandes'::regclass AND conname = :nom",
        nom=CONTRAINTE,
    )


async def _inserer(url: str, *, email: str | None, canal: str | None = "") -> uuid.UUID:
    """Commande synthétique ; `canal` = "" : colonne non renseignée (base en 0004)."""
    identifiant = uuid.uuid4()
    colonnes = "id, client, email, cle_idempotence, seance_id, statut, montant_total, cree_le,"
    colonnes += " expire_le, paiement_demande"
    valeurs = ":id, :client, :email, NULL, :seance, 'EN_ATTENTE', 4500, :cree, :expire, false"
    parametres: dict[str, Any] = {
        "id": identifiant,
        "client": f"client-test-{identifiant}",
        "email": email,
        "seance": uuid.uuid4(),
        "cree": datetime.now(UTC),
        "expire": datetime.now(UTC) + timedelta(minutes=10),
    }
    if canal != "":
        colonnes += ", canal"
        valeurs += ", :canal"
        parametres["canal"] = canal
    await _executer(
        url,
        f"INSERT INTO commandes ({colonnes}) VALUES ({valeurs})",  # noqa: S608
        **parametres,
    )
    return identifiant


async def test_la_migration_0005_ajoute_un_canal_non_nul_borne_par_sa_contrainte(
    serveur: Any, migration: Callable[..., None]
) -> None:
    url = await _base_neuve(serveur)
    await _migrer(migration, "commandes", url)

    colonne = await _colonne_canal(url)
    assert colonne, "colonne canal absente de commandes après upgrade head"
    assert colonne[0]["is_nullable"] == "NO", colonne
    assert colonne[0]["column_default"] is None, colonne
    contrainte = await _contrainte(url)
    assert contrainte, f"contrainte {CONTRAINTE} absente"
    assert "DIRECT" in contrainte[0]["def"] and "PARTENAIRE" in contrainte[0]["def"], contrainte

    with pytest.raises(IntegrityError) as hors_liste:
        await _inserer(url, email="client.test@exemple.test", canal="AUTRE")
    assert CONTRAINTE in str(hors_liste.value)
    with pytest.raises(IntegrityError) as nul:
        await _inserer(url, email="client.test@exemple.test", canal=None)
    assert "canal" in str(nul.value)

    await _migrer(migration, "commandes", url, "0004", "downgrade")
    assert await _colonne_canal(url) == []
    assert await _contrainte(url) == []

    await _migrer(migration, "commandes", url)
    assert await _colonne_canal(url), "colonne canal absente après le nouvel upgrade"
    assert await _contrainte(url), f"contrainte {CONTRAINTE} absente après le nouvel upgrade"


async def test_la_migration_rattache_les_commandes_existantes_a_leur_canal(
    serveur: Any, migration: Callable[..., None]
) -> None:
    url = await _base_neuve(serveur)
    await _migrer(migration, "commandes", url, "0004")
    directe = await _inserer(url, email="client.test@exemple.test")
    partenaire = await _inserer(url, email=None)

    await _migrer(migration, "commandes", url)

    assert await _colonne_canal(url), "colonne canal absente de commandes après upgrade head"
    lignes = {
        ligne["id"]: ligne["canal"]
        for ligne in await _executer(url, "SELECT id, canal FROM commandes")
    }
    assert lignes == {directe: "DIRECT", partenaire: "PARTENAIRE"}
