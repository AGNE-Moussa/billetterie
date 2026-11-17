"""BIL-011, CA1 (Q1, Q2) : remboursements sous livraisons et paiements simultanés (plan
docs/test-plans/BIL-011.md).

Traitements lancés ensemble derrière une barrière, chacun dans sa session et sa transaction, sur
la vraie base migrée ; `POST /api/v1/payments` par l'application sous lifespan. Un paiement
n'est remboursé qu'une fois, et aucun paiement `ACCEPTE` ne survit à l'annulation de sa séance.
Marqueur `concurrence` : joué par `make test-concurrence`.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from commun.consommateurs import traiter_une_fois
from commun.evenements import Evenement
from commun.verrou_seance import verrouiller_seance
from paiements.consommateurs import (
    rembourser_paiement_de_la_commande,
    rembourser_paiements_de_la_seance,
)

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

CORRELATION = "correlation-bil-011-1"
CONSOMMATEUR_SEANCE = "paiements.show-cancelled"
CONSOMMATEUR_REFUS = "paiements.ticket-rejected"
REMBOURSE = "ticketing.payment.refunded"
TOURS = 20


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    moteur = create_async_engine(
        database_url, pool_size=12, connect_args={"timeout": 30, "command_timeout": 30}
    )
    try:
        yield async_sessionmaker(moteur, expire_on_commit=False)
    finally:
        await moteur.dispose()


def show_cancelled(seance_id: uuid.UUID) -> Evenement:
    return Evenement(
        type="ticketing.show.cancelled",
        correlation_id=CORRELATION,
        data={"seance_id": str(seance_id), "evenement_id": str(uuid.uuid4())},
    )


def ticket_rejected(commande_id: uuid.UUID, seance_id: uuid.UUID) -> Evenement:
    return Evenement(
        type="ticketing.ticket.rejected",
        correlation_id=CORRELATION,
        data={
            "commande_id": str(commande_id),
            "seance_id": str(seance_id),
            "place_ids": [str(uuid.uuid4())],
            "motif": "SEANCE_ANNULEE",
        },
    )


def annulation(sessions: Any, evenement: Evenement) -> Awaitable[bool]:
    return traiter_une_fois(
        sessions, CONSOMMATEUR_SEANCE, rembourser_paiements_de_la_seance, evenement
    )


def refus(sessions: Any, evenement: Evenement) -> Awaitable[bool]:
    return traiter_une_fois(
        sessions, CONSOMMATEUR_REFUS, rembourser_paiement_de_la_commande, evenement
    )


async def ensemble(*appels: Awaitable[Any]) -> list[Any]:
    """Lance tout ensemble derrière une barrière ; rend le résultat ou l'exception de chacun."""
    depart = asyncio.Event()

    async def lancer(appel: Awaitable[Any]) -> Any:
        await depart.wait()
        try:
            return await appel
        except Exception as erreur:  # noqa: BLE001 : classée par le test
            return erreur

    taches = [asyncio.create_task(lancer(appel)) for appel in appels]
    await asyncio.sleep(0)
    depart.set()
    return list(await asyncio.wait_for(asyncio.gather(*taches), timeout=120))


async def remboursements(base: Any, paiement_id: Any) -> list[dict[str, Any]]:
    lignes = await base.lignes("SELECT * FROM outbox WHERE type = :t", t=REMBOURSE)
    return [ligne for ligne in lignes if ligne["data"].get("paiement_id") == str(paiement_id)]


async def payer(service: Any, outils: Any, commande_id: uuid.UUID, seance_id: uuid.UUID) -> Any:
    reponse = await service.payer(commande_id=commande_id, seance_id=seance_id, montant=9000)
    return outils.exiger_statut(reponse, 201, f"paiement préalable de {commande_id}")


async def test_show_cancelled_et_ticket_rejected_simultanes_ne_remboursent_qu_une_fois(
    service: Any, base: Any, sessions: Any, outils: Any
) -> None:
    for tour in range(1, TOURS + 1):
        s, c1 = uuid.uuid4(), uuid.uuid4()
        p1 = await payer(service, outils, c1, s)

        resultats = await ensemble(
            annulation(sessions, show_cancelled(s)), refus(sessions, ticket_rejected(c1, s))
        )

        publies = await remboursements(base, p1["id"])
        assert len(publies) == 1, f"tour {tour} : {len(publies)} payment.refunded pour P1"
        erreurs = [r for r in resultats if isinstance(r, BaseException)]
        assert erreurs == [], f"tour {tour} : {erreurs}"


@pytest.mark.parametrize("livraisons", [2, 10])
async def test_deux_livraisons_simultanees_de_show_cancelled_ne_remboursent_qu_une_fois(
    livraisons: int, service: Any, base: Any, sessions: Any, outils: Any
) -> None:
    s = uuid.uuid4()
    acceptes = [await payer(service, outils, uuid.uuid4(), s) for _ in range(2)]
    message = show_cancelled(s)

    await ensemble(*(annulation(sessions, message) for _ in range(livraisons)))

    for paiement in acceptes:
        publies = await remboursements(base, paiement["id"])
        assert len(publies) == 1, f"{len(publies)} payment.refunded pour {paiement['id']}"


@pytest.mark.parametrize("livraisons", [2, 10])
async def test_le_meme_show_cancelled_sous_des_id_differents_ne_rembourse_qu_une_fois(
    livraisons: int, service: Any, base: Any, sessions: Any, outils: Any
) -> None:
    """Review BIL-011, point 1 : même `data` sous un autre `id` (republication), en parallèle ;
    seul le passage conditionnel `ACCEPTE` → `REMBOURSE` protège alors l'argent."""
    s = uuid.uuid4()
    acceptes = [await payer(service, outils, uuid.uuid4(), s) for _ in range(2)]

    resultats = await ensemble(
        *(annulation(sessions, show_cancelled(s)) for _ in range(livraisons))
    )

    for paiement in acceptes:
        publies = await remboursements(base, paiement["id"])
        assert len(publies) == 1, f"{len(publies)} payment.refunded pour {paiement['id']}"
    erreurs = [r for r in resultats if isinstance(r, BaseException)]
    assert erreurs == [], erreurs


async def test_un_paiement_attendant_une_annulation_plus_longue_que_delai_base_renvoie_503_puis_se_rejoue(  # noqa: E501 : nom explicite
    service_paiements: Any, base: Any, sessions: Any, outils: Any
) -> None:
    """Review BIL-011, point 7 : l'annulation tient le verrou exclusif de la séance plus de
    `delai_base` secondes ; le paiement répond 503 sans ligne, puis son rejeu (même clé) voit
    la séance annulée."""
    s, c2 = uuid.uuid4(), uuid.uuid4()
    async with service_paiements(delai_base=1.0) as service:
        async with sessions() as session, session.begin():
            await verrouiller_seance(session, s, exclusif=True)
            reponse = await service.payer(commande_id=c2, seance_id=s, montant=4500)
            await session.execute(
                sa.text("INSERT INTO seances_annulees (seance_id, annulee_le) VALUES (:s, now())"),
                {"s": s},
            )

        outils.exiger_probleme(reponse, 503, "BASE_INDISPONIBLE", "paiement bloqué par le verrou")
        assert await base.lignes("SELECT * FROM paiements WHERE commande_id = :c", c=c2) == []

        rejeu = await service.payer(commande_id=c2, seance_id=s, montant=4500)

        outils.exiger_probleme(rejeu, 409, "SHOW_CANCELLED", "rejeu après l'annulation")
        assert await base.lignes("SELECT * FROM paiements WHERE commande_id = :c", c=c2) == []


async def test_un_paiement_simultane_a_l_annulation_est_refuse_ou_rembourse(
    service: Any, base: Any, sessions: Any, outils: Any
) -> None:
    for tour in range(1, TOURS + 1):
        s, c2 = uuid.uuid4(), uuid.uuid4()

        reponse, _ = await ensemble(
            service.payer(commande_id=c2, seance_id=s, montant=4500),
            annulation(sessions, show_cancelled(s)),
        )

        assert not isinstance(reponse, BaseException), f"tour {tour} : {reponse!r}"
        lignes = await base.lignes("SELECT * FROM paiements WHERE commande_id = :c", c=c2)
        if reponse.status_code == 409:
            assert reponse.json()["code"] == "SHOW_CANCELLED", f"tour {tour} : {reponse.text}"
            assert lignes == [], f"tour {tour} : {lignes}"
        else:
            assert reponse.status_code == 201, f"tour {tour} : {reponse.text}"
            assert [ligne["statut"] for ligne in lignes] == ["REMBOURSE"], (
                f"tour {tour} : paiement {[ligne['statut'] for ligne in lignes]}"
            )
            publies = await remboursements(base, lignes[0]["id"])
            assert len(publies) == 1, f"tour {tour} : {len(publies)} payment.refunded"
