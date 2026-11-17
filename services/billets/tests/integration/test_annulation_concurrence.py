"""BIL-011, CA3 (Q3) : annulation de la séance et émission des billets traitées en parallèle
(plan docs/test-plans/BIL-011.md).

`ticketing.show.cancelled` (file `billets.show-cancelled`) et `ticketing.order.confirmed` (file
`billets.order-confirmed`) sont traités ensemble, derrière une barrière, chacun dans sa session
et sa transaction, sur la vraie base et le vrai Redis du module, 20 tours. Le verrou consultatif
de la séance (partagé à l'émission, exclusif à l'annulation) ne doit laisser aucun billet `EMIS`.
Marqueur `concurrence` : joué par `make test-concurrence`.
"""

import asyncio
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from billets.consommateurs import annuler_billets_de_la_seance, recevoir_commande_confirmee
from billets.infra.verrous import VerrousRedis
from commun.consommateurs import traiter_une_fois
from commun.evenements import Evenement

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

CONSOMMATEUR = "billets.show-cancelled"
CORRELATION = "correlation-bil-011-1"
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
    magasin = VerrousRedis(redis_url, 0.5)
    try:
        yield magasin
    finally:
        await magasin.fermer()


def show_cancelled(seance_id: uuid.UUID) -> Evenement:
    return Evenement(
        type="ticketing.show.cancelled",
        correlation_id=CORRELATION,
        data={"seance_id": str(seance_id), "evenement_id": str(uuid.uuid4())},
    )


def order_confirmed(seance: Any, libelles: list[str], client: str, email: str) -> Evenement:
    return Evenement(
        type="ticketing.order.confirmed",
        correlation_id=CORRELATION,
        data={
            "commande_id": str(uuid.uuid4()),
            "client": client,
            "email": email,
            "seance_id": str(seance.id),
            "lignes": [{"place_id": str(seance.places[x]), "montant": 4500} for x in libelles],
            "montant_total": 4500 * len(libelles),
        },
    )


async def ensemble(*appels: Awaitable[Any]) -> list[BaseException | None]:
    """Lance tous les traitements ensemble, derrière une barrière ; rend l'exception de chacun
    (ou None)."""
    depart = asyncio.Event()

    async def lancer(appel: Awaitable[Any]) -> BaseException | None:
        await depart.wait()
        try:
            await appel
        except Exception as erreur:  # noqa: BLE001 : classée par le test
            return erreur
        return None

    taches = [asyncio.create_task(lancer(appel)) for appel in appels]
    await asyncio.sleep(0)
    depart.set()
    return list(await asyncio.wait_for(asyncio.gather(*taches), timeout=120))


async def billets_de(base: Any, commande_id: str) -> list[Any]:
    return await base.lignes(  # type: ignore[no-any-return]
        "SELECT * FROM billets WHERE commande_id = :c", c=uuid.UUID(commande_id)
    )


async def refus_de(base: Any, commande_id: str) -> list[Any]:
    lignes = await base.lignes("SELECT * FROM outbox WHERE type = :t", t=BILLETS_REFUSES)
    return [ligne for ligne in lignes if ligne["data"].get("commande_id") == commande_id]


async def test_annulation_et_emission_simultanees_ne_laissent_aucun_billet_emis(
    base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    for tour in range(1, TOURS + 1):
        seance = await base.semer_seance()
        c1 = order_confirmed(seance, ["A1", "A2"], "client-test", "client.test@exemple.test")
        commande_id = c1.data["commande_id"]

        erreurs = await ensemble(
            traiter_une_fois(
                sessions, CONSOMMATEUR, annuler_billets_de_la_seance, show_cancelled(seance.id)
            ),
            recevoir_commande_confirmee(sessions, verrous, c1),
        )

        emis = await base.lignes(
            "SELECT * FROM billets WHERE seance_id = :s AND statut = 'EMIS'", s=seance.id
        )
        assert emis == [], f"tour {tour} : {len(emis)} billets EMIS après l'annulation"
        billets = await billets_de(base, commande_id)
        refus = await refus_de(base, commande_id)
        annules_sans_refus = [b["statut"] for b in billets] == ["ANNULE"] * 2 and refus == []
        refus_sans_billet = billets == [] and [r["data"]["motif"] for r in refus] == [
            "SEANCE_ANNULEE"
        ]
        assert annules_sans_refus or refus_sans_billet, (
            f"tour {tour} : billets {[b['statut'] for b in billets]}, refus {refus}"
        )
        assert [e for e in erreurs if e is not None] == [], f"tour {tour} : {erreurs}"


async def test_deux_commandes_disputant_la_meme_place_pendant_l_annulation_n_obtiennent_aucun_billet_emis(  # noqa: E501 : nom du plan
    base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    for tour in range(1, TOURS + 1):
        seance = await base.semer_seance()
        c1 = order_confirmed(seance, ["A1"], "client-test", "client.test@exemple.test")
        c5 = order_confirmed(seance, ["A1"], "client-c5-test", "client2.test@exemple.test")

        erreurs = await ensemble(
            recevoir_commande_confirmee(sessions, verrous, c1),
            recevoir_commande_confirmee(sessions, verrous, c5),
            traiter_une_fois(
                sessions, CONSOMMATEUR, annuler_billets_de_la_seance, show_cancelled(seance.id)
            ),
        )

        sur_a1 = await base.lignes(
            "SELECT * FROM billets WHERE seance_id = :s AND place_id = :p",
            s=seance.id,
            p=seance.places["A1"],
        )
        assert len(sur_a1) <= 1, f"tour {tour} : {len(sur_a1)} billets sur A1"
        assert [b["statut"] for b in sur_a1 if b["statut"] == "EMIS"] == [], (
            f"tour {tour} : billet EMIS sur A1 après l'annulation"
        )
        for commande in (c1, c5):
            commande_id = commande.data["commande_id"]
            if not await billets_de(base, commande_id):
                assert len(await refus_de(base, commande_id)) == 1, (
                    f"tour {tour} : commande {commande_id} sans billet ni ticket.rejected"
                )
        integrite = [e for e in erreurs if isinstance(e, IntegrityError)]
        assert integrite == [], f"tour {tour} : {integrite}"
