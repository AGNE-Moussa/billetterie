"""CA2, E6, E7 et E9 (BIL-008, décisions Q6, Q9, Q10, Q20, Q21) : un seul paiement par commande
sur la vraie base, même sous des requêtes simultanées ; séance annulée ; base injoignable ;
migrations.

Hors marqueur `concurrence` : la garantie porte sur le débit unique d'une commande
(`uq_paiements_commande_id`), pas sur la vente d'une place ; ces cas restent dans
`make test-integration`.
"""

import asyncio
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

pytestmark = pytest.mark.anyio

SIMULTANES = 10
DELAI_BASE = 1.0
REPONSE_BASE_MAXIMALE = DELAI_BASE + 5.0


async def _simultanes(nombre: int, appel: Any) -> list[Any]:
    depart = asyncio.Event()

    async def tache(numero: int) -> Any:
        await depart.wait()
        return await appel(numero)

    taches = [asyncio.create_task(tache(n)) for n in range(nombre)]
    await asyncio.sleep(0)
    depart.set()
    return list(await asyncio.gather(*taches))


# --- CA2 ---------------------------------------------------------------------------------------


async def test_dix_paiements_simultanes_de_la_meme_commande_ne_debitent_qu_une_fois(
    service: Any, base: Any, outils: Any
) -> None:
    commande_id, seance_id = uuid.uuid4(), uuid.uuid4()

    reponses = await _simultanes(
        SIMULTANES, lambda _n: service.payer(commande_id=commande_id, seance_id=seance_id)
    )

    assert Counter(r.status_code for r in reponses) == {201: SIMULTANES}, [r.text for r in reponses]
    assert len({r.json()["id"] for r in reponses}) == 1
    assert len(await base.paiements()) == 1


async def test_des_paiements_simultanes_de_montants_differents_n_enregistrent_qu_un_paiement(
    service: Any, base: Any, outils: Any
) -> None:
    commande_id, seance_id = uuid.uuid4(), uuid.uuid4()

    reponses = await _simultanes(
        SIMULTANES,
        lambda n: service.payer(commande_id=commande_id, seance_id=seance_id, montant=4500 + n),
    )

    statuts = Counter(r.status_code for r in reponses)
    assert statuts == {201: 1, 409: SIMULTANES - 1}, [r.text for r in reponses]
    assert all(
        r.json()["code"] == "PAYMENT_ALREADY_EXISTS" for r in reponses if r.status_code == 409
    )
    assert len(await base.paiements()) == 1


async def test_la_base_refuse_un_second_paiement_pour_la_meme_commande(base: Any) -> None:
    commande_id = uuid.uuid4()
    insertion = sa.text(
        "INSERT INTO paiements (id, commande_id, seance_id, montant, statut, cree_le)"
        " VALUES (:id, :commande_id, :seance_id, 4500, 'ACCEPTE', :le)"
    )
    moteur = create_async_engine(base.url, poolclass=NullPool)
    try:
        async with moteur.begin() as connexion:
            await connexion.execute(
                insertion,
                {
                    "id": uuid.uuid4(),
                    "commande_id": commande_id,
                    "seance_id": uuid.uuid4(),
                    "le": datetime.now(UTC),
                },
            )
        with pytest.raises(IntegrityError) as erreur:
            async with moteur.begin() as connexion:
                await connexion.execute(
                    insertion,
                    {
                        "id": uuid.uuid4(),
                        "commande_id": commande_id,
                        "seance_id": uuid.uuid4(),
                        "le": datetime.now(UTC),
                    },
                )
    finally:
        await moteur.dispose()

    assert "uq_paiements_commande_id" in str(erreur.value)


# --- E6 ----------------------------------------------------------------------------------------


async def test_un_paiement_pour_une_seance_annulee_renvoie_409_sans_ligne(
    service: Any, base: Any, outils: Any
) -> None:
    seance_id = uuid.uuid4()
    await base.annuler(seance_id)

    reponse = await service.payer(commande_id=uuid.uuid4(), seance_id=seance_id)

    outils.exiger_probleme(reponse, 409, "SHOW_CANCELLED", "séance annulée")
    assert await base.paiements() == []


async def test_un_paiement_enregistre_se_rejoue_meme_apres_annulation(
    service: Any, base: Any, outils: Any
) -> None:
    commande_id, seance_id = uuid.uuid4(), uuid.uuid4()
    premier = await service.payer(commande_id=commande_id, seance_id=seance_id)
    corps = outils.exiger_statut(premier, 201, "premier paiement")
    await base.annuler(seance_id)

    rejeu = await service.payer(commande_id=commande_id, seance_id=seance_id)

    assert outils.exiger_statut(rejeu, 201, "rejeu après annulation")["id"] == corps["id"]


# --- E7 ----------------------------------------------------------------------------------------


async def test_base_injoignable_creer_paiement_renvoie_503(
    service_paiements: Any, base: Any, postgres: PostgresContainer, outils: Any
) -> None:
    async with service_paiements(delai_base=DELAI_BASE) as service:
        commande_id = uuid.uuid4()
        appel = service.payer(commande_id=commande_id, seance_id=uuid.uuid4())
        conteneur = postgres.get_wrapped_container()
        conteneur.pause()
        try:
            reponse = await outils.borne(
                "creerPaiement, base en pause", appel, REPONSE_BASE_MAXIMALE
            )
        finally:
            conteneur.unpause()

    outils.exiger_probleme(reponse, 503, "BASE_INDISPONIBLE", "creerPaiement, base en pause")
    assert "postgresql" not in reponse.text.lower()


# --- E9 ----------------------------------------------------------------------------------------


async def test_les_migrations_de_paiements_creent_le_modele(base: Any) -> None:
    tables = {
        t["table_name"]
        for t in await base.lignes(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
    }
    assert {"paiements", "seances_annulees", "outbox", "messages_traites"} <= tables, tables
    contraintes = {
        c["conname"]: c["def"]
        for c in await base.lignes(
            "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint"
            " WHERE conrelid = 'paiements'::regclass"
        )
    }
    assert "UNIQUE (commande_id)" in contraintes.values(), contraintes
    assert any(d.startswith("CHECK") and "montant > 0" in d for d in contraintes.values()), (
        contraintes
    )
    assert await base.lignes("SELECT * FROM seances_annulees") == []
