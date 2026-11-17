"""BIL-011, CA1 (Q2, Q4, Q5) : commandes et paiements simultanés à l'annulation d'une séance
(plan docs/test-plans/BIL-011.md).

Plateforme du conftest : deux Commandes, vrais Billets et Paiements en ASGI, PostgreSQL et Redis
réels. `ticketing.show.cancelled` est traité par les consommateurs de Commandes
(`commandes.show-cancelled`) et de Paiements (`paiements.show-cancelled`), chacun dans sa
session sur sa base, en même temps que les appels à l'API (barrière) ; puis chaque
`ticketing.payment.refunded` rangé dans l'outbox de Paiements est délivré au consommateur
`commandes.payment-refunded`. 20 tours. Marqueur `concurrence` : joué par
`make test-concurrence`.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from commandes.consommateurs import (
    enregistrer_paiement_rembourse,
    expirer_commandes_de_la_seance_annulee,
)
from commun.consommateurs import traiter_une_fois
from commun.evenements import Evenement
from paiements.consommateurs import rembourser_paiements_de_la_seance

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

CORRELATION = "correlation-bil-011-1"
TOURS = 20
DUREE_VERROU_MS = 600_000


@pytest.fixture
async def sessions_paiements(
    urls: dict[str, str],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    moteur = create_async_engine(
        urls["paiements"], connect_args={"timeout": 30, "command_timeout": 30}
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
    return list(await asyncio.wait_for(asyncio.gather(*taches), timeout=180))


async def delivrer_remboursements(
    bases: Any, sessions_commandes: Any, seance_id: uuid.UUID
) -> list[BaseException]:
    """Délivre à Commandes chaque payment.refunded de la séance rangé dans l'outbox de
    Paiements, comme le ferait le relais ; rend les exceptions des traitements."""
    erreurs: list[BaseException] = []
    lignes = await bases.paiements.lignes(
        "SELECT * FROM outbox WHERE type = 'ticketing.payment.refunded'"
    )
    for ligne in lignes:
        if ligne["data"].get("seance_id") != str(seance_id):
            continue
        evenement = Evenement(
            id=ligne["id"],
            type=ligne["type"],
            version=ligne["version"],
            occurred_at=ligne["occurred_at"],
            correlation_id=ligne["correlation_id"],
            data=ligne["data"],
        )
        try:
            await traiter_une_fois(
                sessions_commandes,
                "commandes.payment-refunded",
                enregistrer_paiement_rembourse,
                evenement,
            )
        except Exception as erreur:  # noqa: BLE001 : classée par le test
            erreurs.append(erreur)
    return erreurs


def annulations(
    sessions_commandes: Any,
    sessions_paiements: Any,
    seance_id: uuid.UUID,
    message: Evenement | None = None,
) -> list[Awaitable[bool]]:
    message = message or show_cancelled(seance_id)
    return [
        traiter_une_fois(
            sessions_commandes,
            "commandes.show-cancelled",
            expirer_commandes_de_la_seance_annulee,
            message,
        ),
        traiter_une_fois(
            sessions_paiements,
            "paiements.show-cancelled",
            rembourser_paiements_de_la_seance,
            message,
        ),
    ]


async def test_un_paiement_simultane_a_l_annulation_ne_laisse_aucune_commande_confirmee_sans_remboursement(  # noqa: E501 : nom du plan
    plateforme: Any, bases: Any, sessions_commandes: Any, sessions_paiements: Any, outils: Any
) -> None:
    client_b = outils.clients["B"]["sujet"]
    for tour in range(1, TOURS + 1):
        seance = await plateforme.nouvelle_seance()
        # C2 EN_ATTENTE (réservation finie, paiement à refaire), B1 verrouillée pour elle.
        c2 = await bases.ajouter_commande(
            expire_le=datetime.now(UTC) + timedelta(minutes=10),
            seance_id=seance.id,
            place_ids=[seance.places["B1"]],
            client=client_b,
        )
        await plateforme.redis.poser(
            plateforme.cle_redis("B1", seance), str(c2.id), DUREE_VERROU_MS
        )

        paiement, *traitements = await ensemble(
            plateforme.payer("B", str(c2.id)),
            *annulations(sessions_commandes, sessions_paiements, seance.id),
        )
        erreurs = [t for t in traitements if isinstance(t, BaseException)]
        erreurs += await delivrer_remboursements(bases, sessions_commandes, seance.id)

        assert isinstance(paiement, httpx.Response), f"tour {tour} : {paiement!r}"
        assert paiement.status_code < 500, f"tour {tour} : {paiement.status_code} {paiement.text}"
        statut = await bases.statut(c2.id)
        paiements = [p["statut"] for p in await bases.paiements_de(c2.id)]
        confirmations = await bases.evenements_de("ticketing.order.confirmed", str(c2.id))
        expiree_sans_confirmation = statut == "EXPIREE" and confirmations == []
        remboursee = statut == "REMBOURSEE" and paiements == ["REMBOURSE"]
        assert expiree_sans_confirmation or remboursee, (
            f"tour {tour} : commande {statut}, paiement {paiements},"
            f" {len(confirmations)} order.confirmed"
        )
        assert "ACCEPTE" not in paiements, f"tour {tour} : paiement ACCEPTE restant"
        assert erreurs == [], f"tour {tour} : {erreurs}"


async def test_annulation_paiement_tache_d_expiration_et_seconde_livraison_simultanees_ne_publient_qu_un_order_expired(  # noqa: E501 : nom explicite
    plateforme: Any, bases: Any, sessions_commandes: Any, sessions_paiements: Any, outils: Any
) -> None:
    """Review BIL-011, point 5 : le `SELECT … FOR UPDATE ORDER BY id` de `show.cancelled`
    tourne en même temps que `payerCommande`, un cycle de la tâche d'expiration (BIL-010) et
    une seconde livraison du même `data` sous un autre `id` : un seul `order.expired` par
    commande, aucun interblocage, aucune commande `EN_ATTENTE` ou `CONFIRMEE` restante."""
    client_b = outils.clients["B"]["sujet"]
    for tour in range(1, TOURS + 1):
        seance = await plateforme.nouvelle_seance()
        c2 = await bases.ajouter_commande(
            expire_le=datetime.now(UTC) + timedelta(minutes=10),
            seance_id=seance.id,
            place_ids=[seance.places["B1"]],
            client=client_b,
        )
        await plateforme.redis.poser(
            plateforme.cle_redis("B1", seance), str(c2.id), DUREE_VERROU_MS
        )
        for _ in range(3):  # échues : la tâche d'expiration les vise aussi
            await bases.ajouter_commande(
                expire_le=datetime.now(UTC) - timedelta(minutes=1), seance_id=seance.id, places=1
            )
        for _ in range(2):  # en attente sans échéance
            await bases.ajouter_commande(expire_le=None, seance_id=seance.id, places=1)
        message = show_cancelled(seance.id)
        doublon = Evenement(**{**message.model_dump(), "id": uuid.uuid4()})

        paiement, cycle, *traitements = await ensemble(
            plateforme.payer("B", str(c2.id)),
            plateforme.cycle(1),
            *annulations(sessions_commandes, sessions_paiements, seance.id, message),
            traiter_une_fois(
                sessions_commandes,
                "commandes.show-cancelled",
                expirer_commandes_de_la_seance_annulee,
                doublon,
            ),
        )
        erreurs = [t for t in [cycle, *traitements] if isinstance(t, BaseException)]
        erreurs += await delivrer_remboursements(bases, sessions_commandes, seance.id)

        assert isinstance(paiement, httpx.Response), f"tour {tour} : {paiement!r}"
        assert paiement.status_code < 500, f"tour {tour} : {paiement.status_code} {paiement.text}"
        assert erreurs == [], f"tour {tour} : {erreurs}"
        commandes = await bases.commandes.lignes(
            "SELECT id, statut FROM commandes WHERE seance_id = :s", s=seance.id
        )
        restantes = [c["statut"] for c in commandes if c["statut"] in ("EN_ATTENTE", "CONFIRMEE")]
        assert restantes == [], f"tour {tour} : commandes {restantes} après l'annulation"
        for commande in commandes:
            expirees = await bases.evenements_de("ticketing.order.expired", str(commande["id"]))
            attendu = {1} if commande["statut"] == "EXPIREE" else {0}
            if commande["id"] == c2.id and paiement.status_code == 409:
                # payerCommande a reverrouillé les places de C2 déjà expirée : expiration
                # republiée pour que Billets les libère (review BIL-010, point 1), même data.
                attendu = {1, 2}
                assert len({str(sorted(e["data"].items())) for e in expirees}) == 1, (
                    f"tour {tour} : order.expired de C2 différents : {expirees}"
                )
            assert len(expirees) in attendu, (
                f"tour {tour} : commande {commande['statut']}, {len(expirees)} order.expired"
            )
        assert "ACCEPTE" not in [p["statut"] for p in await bases.paiements_de(c2.id)], (
            f"tour {tour} : paiement ACCEPTE restant"
        )


async def test_deux_clients_disputant_la_meme_place_pendant_l_annulation_ne_gardent_ni_place_ni_debit(  # noqa: E501 : nom du plan
    plateforme: Any, bases: Any, sessions_commandes: Any, sessions_paiements: Any
) -> None:
    for tour in range(1, TOURS + 1):
        seance = await plateforme.nouvelle_seance()

        reponse_a, reponse_b, *traitements = await ensemble(
            plateforme.commander("A", ["A1"], seance=seance, instance=plateforme.instance(0)),
            plateforme.commander("B", ["A1"], seance=seance, instance=plateforme.instance(1)),
            *annulations(sessions_commandes, sessions_paiements, seance.id),
        )
        erreurs = [t for t in traitements if isinstance(t, BaseException)]
        erreurs += await delivrer_remboursements(bases, sessions_commandes, seance.id)

        reponses = [reponse_a, reponse_b]
        assert all(isinstance(r, httpx.Response) for r in reponses), f"tour {tour} : {reponses}"
        creees = [r for r in reponses if r.status_code == 201]
        assert len(creees) <= 1, f"tour {tour} : {len(creees)} commandes ont obtenu A1"
        for reponse in reponses:
            if reponse.status_code != 201:
                assert reponse.status_code == 409, f"tour {tour} : {reponse.text}"
                assert reponse.json()["code"] in ("SEAT_ALREADY_TAKEN", "SHOW_CANCELLED"), (
                    f"tour {tour} : {reponse.text}"
                )
        commandes = await bases.commandes.lignes(
            "SELECT id, statut FROM commandes WHERE seance_id = :s", s=seance.id
        )
        restantes = [c["statut"] for c in commandes if c["statut"] in ("EN_ATTENTE", "CONFIRMEE")]
        assert restantes == [], f"tour {tour} : commandes {restantes} après l'annulation"
        for commande in commandes:
            if commande["statut"] == "EXPIREE":
                expirees = await bases.evenements_de("ticketing.order.expired", str(commande["id"]))
                assert len(expirees) == 1, f"tour {tour} : {len(expirees)} order.expired"
        assert erreurs == [], f"tour {tour} : {erreurs}"
