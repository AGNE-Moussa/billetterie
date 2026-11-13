"""BIL-009, CA3 et E1 : livraisons simultanées de ticketing.order.confirmed (plan
docs/test-plans/BIL-009.md).

Le traitement d'une livraison (`recevoir_commande_confirmee`) est lancé N fois en parallèle
(`asyncio.gather`), chaque appel dans sa propre session et sa transaction, sur la vraie base et
le vrai Redis du module. Verrous Redis absents : seule la base (`uq_billets_place`,
`messages_traites`) départage. Marqueur `concurrence` : joué par `make test-concurrence`.
"""

import asyncio
import secrets
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from billets.consommateurs import recevoir_commande_confirmee
from billets.infra.verrous import VerrousRedis
from commun.evenements import Evenement

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

CORRELATION = "correlation-bil-009-1"
BILLET_EMIS = "ticketing.ticket.issued"
BILLETS_REFUSES = "ticketing.ticket.rejected"
TOURS = 20


@pytest.fixture
def cle_qr(monkeypatch: pytest.MonkeyPatch) -> str:
    cle = secrets.token_urlsafe(32)
    monkeypatch.setenv("QR_CLE_SIGNATURE", cle)
    return cle


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    moteur = create_async_engine(
        database_url, pool_size=10, connect_args={"timeout": 30, "command_timeout": 30}
    )
    try:
        yield async_sessionmaker(moteur, expire_on_commit=False)
    finally:
        await moteur.dispose()


@pytest.fixture
async def verrous(redis_url: str, observateur: Any) -> AsyncIterator[VerrousRedis]:
    """Magasin de verrous sur un Redis vide (aucun verrou posé : la base seule départage)."""
    magasin = VerrousRedis(redis_url, 0.5)
    try:
        yield magasin
    finally:
        await magasin.fermer()


def commande(seance: Any, libelles: list[str], client: str, email: str) -> dict[str, Any]:
    return {
        "commande_id": str(uuid.uuid4()),
        "client": client,
        "email": email,
        "seance_id": str(seance.id),
        "lignes": [{"place_id": str(seance.places[x]), "montant": 4500} for x in libelles],
        "montant_total": 4500 * len(libelles),
    }


def order_confirmed(data: dict[str, Any]) -> Evenement:
    return Evenement(type="ticketing.order.confirmed", correlation_id=CORRELATION, data=data)


async def traiter(
    sessions: async_sessionmaker[AsyncSession], verrous: VerrousRedis, evenement: Evenement
) -> BaseException | None:
    try:
        await recevoir_commande_confirmee(sessions, verrous, evenement)
    except Exception as erreur:  # noqa: BLE001 : classée par le test
        return erreur
    return None


async def ensemble(
    sessions: async_sessionmaker[AsyncSession], verrous: VerrousRedis, *evenements: Evenement
) -> list[BaseException | None]:
    """Lance toutes les livraisons ensemble, derrière une barrière."""
    depart = asyncio.Event()

    async def livrer(evenement: Evenement) -> BaseException | None:
        await depart.wait()
        return await traiter(sessions, verrous, evenement)

    taches = [asyncio.create_task(livrer(e)) for e in evenements]
    await asyncio.sleep(0)
    depart.set()
    return list(await asyncio.gather(*taches))


async def billets_de(base: Any, commande_id: str) -> list[Any]:
    return await base.lignes(  # type: ignore[no-any-return]
        "SELECT * FROM billets WHERE commande_id = :c", c=uuid.UUID(commande_id)
    )


async def evenements_de(base: Any, type_evenement: str, commande_id: str) -> list[Any]:
    lignes = await base.lignes("SELECT * FROM outbox WHERE type = :type", type=type_evenement)
    return [ligne for ligne in lignes if ligne["data"].get("commande_id") == commande_id]


@pytest.mark.parametrize("livraisons", [2, 10])
async def test_deux_livraisons_simultanees_du_meme_order_confirmed_n_emettent_qu_un_billet_par_place(  # noqa: E501 : nom du plan
    livraisons: int, seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    data = commande(seance, ["A1", "A2"], "client-test", "client.test@exemple.test")
    message = order_confirmed(data)

    erreurs = await ensemble(sessions, verrous, *([message] * livraisons))

    assert len(await billets_de(base, data["commande_id"])) == 2
    assert len(await evenements_de(base, BILLET_EMIS, data["commande_id"])) == 2
    assert await evenements_de(base, BILLETS_REFUSES, data["commande_id"]) == []
    assert [e for e in erreurs if e is not None] == []


async def test_deux_commandes_simultanees_sur_la_meme_place_n_obtiennent_qu_un_billet_et_l_autre_est_rejetee(  # noqa: E501 : nom du plan
    base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    for tour in range(1, TOURS + 1):
        seance = await base.semer_seance()
        a1 = str(seance.places["A1"])
        c1 = commande(seance, ["A1", "A2"], "client-test", "client.test@exemple.test")
        c2 = commande(seance, ["A1"], "client-b-test", "client.b.test@exemple.test")

        erreurs = await ensemble(sessions, verrous, order_confirmed(c1), order_confirmed(c2))

        sur_a1 = await base.lignes(
            "SELECT commande_id FROM billets WHERE seance_id = :s AND place_id = :p",
            s=seance.id,
            p=seance.places["A1"],
        )
        assert len(sur_a1) == 1, f"tour {tour} : {len(sur_a1)} billets sur A1"
        gagnante, perdante = (
            (c1, c2) if str(sur_a1[0]["commande_id"]) == c1["commande_id"] else (c2, c1)
        )
        nombre = len(gagnante["lignes"])
        assert len(await billets_de(base, gagnante["commande_id"])) == nombre, f"tour {tour}"
        emis = await evenements_de(base, BILLET_EMIS, gagnante["commande_id"])
        assert len(emis) == nombre, f"tour {tour}"
        assert await billets_de(base, perdante["commande_id"]) == [], f"tour {tour}"
        refus = await evenements_de(base, BILLETS_REFUSES, perdante["commande_id"])
        assert [(r["data"]["motif"], r["data"]["place_ids"]) for r in refus] == [
            ("PLACE_DEJA_VENDUE", [a1])
        ], f"tour {tour}"
        assert [e for e in erreurs if e is not None] == [], f"tour {tour} : {erreurs}"
