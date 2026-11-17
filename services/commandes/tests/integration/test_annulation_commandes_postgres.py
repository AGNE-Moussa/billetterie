"""BIL-011, CA1 (H1, H5, Q5) : consommateurs `ticketing.show.cancelled` et
`ticketing.payment.refunded` de Commandes (plan docs/test-plans/BIL-011.md).

Le traitement d'une livraison (`commun.consommateurs.traiter_une_fois` avec les traitements de
`commandes.consommateurs`, files `commandes.show-cancelled` et `commandes.payment-refunded`) est
appelé directement sur la vraie base de Commandes ; une exception remontée signifierait un
nouvel essai, puis la DLQ. Commandes synthétiques écrites en base (`Bases.ajouter_commande`).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from commandes.consommateurs import (
    enregistrer_paiement_rembourse,
    expirer_commandes_de_la_seance_annulee,
)
from commun.consommateurs import traiter_une_fois
from commun.evenements import Evenement
from paiements.consommateurs import rembourser_paiements_de_la_seance

pytestmark = pytest.mark.anyio

CORRELATION = "correlation-bil-011-1"
CONSOMMATEUR_SEANCE = "commandes.show-cancelled"
CONSOMMATEUR_REMBOURSEMENT = "commandes.payment-refunded"
EXPIREE = "ticketing.order.expired"


def show_cancelled(seance_id: uuid.UUID, identifiant: Any = None) -> Evenement:
    return Evenement(
        id=identifiant or uuid.uuid4(),
        type="ticketing.show.cancelled",
        correlation_id=CORRELATION,
        data={"seance_id": str(seance_id), "evenement_id": str(uuid.uuid4())},
    )


def payment_refunded(commande: Any, montant: int = 9000, identifiant: Any = None) -> Evenement:
    return Evenement(
        id=identifiant or uuid.uuid4(),
        type="ticketing.payment.refunded",
        correlation_id=CORRELATION,
        data={
            "paiement_id": str(uuid.uuid4()),
            "commande_id": str(commande.id),
            "seance_id": str(commande.seance_id),
            "montant": montant,
        },
    )


async def traiter(sessions: Any, evenement: Evenement) -> BaseException | None:
    if evenement.type == "ticketing.show.cancelled":
        nom, traitement = CONSOMMATEUR_SEANCE, expirer_commandes_de_la_seance_annulee
    else:
        nom, traitement = CONSOMMATEUR_REMBOURSEMENT, enregistrer_paiement_rembourse
    try:
        await traiter_une_fois(sessions, nom, traitement, evenement)
    except Exception as erreur:  # noqa: BLE001 : classée par le test
        return erreur
    return None


def echeance() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=10)


async def test_les_commandes_de_la_seance_sont_expirees_en_base_avec_order_expired(
    bases: Any, sessions_commandes: Any, outils: Any
) -> None:
    s = uuid.uuid4()
    c2 = await bases.ajouter_commande(expire_le=echeance(), seance_id=s, places=1)
    c1 = await bases.ajouter_commande(expire_le=None, statut="CONFIRMEE", seance_id=s)

    erreur = await traiter(sessions_commandes, show_cancelled(s))

    assert await bases.statut(c2.id) == "EXPIREE"
    publies = await bases.evenements_de(EXPIREE, str(c2.id))
    assert len(publies) == 1, publies
    (publie,) = publies
    assert publie["data"]["seance_id"] == str(s)
    assert sorted(publie["data"]["place_ids"]) == sorted(str(p) for p in c2.place_ids)
    assert outils.erreurs_evenement(publie) == []
    assert publie["xmin"] == await bases.xmin_commande(str(c2.id))
    assert await bases.statut(c1.id) == "CONFIRMEE"
    assert await bases.evenements_de(EXPIREE, str(c1.id)) == []
    assert erreur is None, repr(erreur)


async def test_show_cancelled_recu_deux_fois_ne_publie_qu_un_order_expired(
    bases: Any, sessions_commandes: Any
) -> None:
    s = uuid.uuid4()
    c2 = await bases.ajouter_commande(expire_le=echeance(), seance_id=s, places=1)
    message = show_cancelled(s)

    erreurs = [
        await traiter(sessions_commandes, message),
        await traiter(sessions_commandes, message),
        await traiter(sessions_commandes, show_cancelled(s)),
    ]

    assert await bases.statut(c2.id) == "EXPIREE"
    assert len(await bases.evenements_de(EXPIREE, str(c2.id))) == 1
    assert [e for e in erreurs if e is not None] == []


async def test_payment_refunded_passe_la_commande_confirmee_en_remboursee(
    plateforme: Any, bases: Any, sessions_commandes: Any, outils: Any
) -> None:
    c1 = await bases.ajouter_commande(expire_le=None, statut="CONFIRMEE")
    client_c1 = {
        "sujet": c1.client,
        "roles": ["customer"],
        "scopes": ["orders:read", "orders:write"],
        "email": "client.test@exemple.test",
    }

    erreur = await traiter(sessions_commandes, payment_refunded(c1))

    assert await bases.statut(c1.id) == "REMBOURSEE"
    lue = outils.exiger_statut(await plateforme.lire(client_c1, str(c1.id)), 200, "lireCommande")
    assert lue["statut"] == "REMBOURSEE"
    assert erreur is None, repr(erreur)


async def test_payment_refunded_recu_deux_fois_ne_change_rien_de_plus(
    bases: Any, sessions_commandes: Any
) -> None:
    c1 = await bases.ajouter_commande(expire_le=None, statut="CONFIRMEE")
    message = payment_refunded(c1)

    erreurs = [await traiter(sessions_commandes, message)]
    erreurs.append(await traiter(sessions_commandes, message))
    erreurs.append(
        await traiter(sessions_commandes, Evenement(**{**message.model_dump(), "id": uuid.uuid4()}))
    )

    assert await bases.statut(c1.id) == "REMBOURSEE"
    assert [e for e in erreurs if e is not None] == []


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


async def delivrer_remboursements(
    bases: Any, sessions_commandes: Any, seance_id: uuid.UUID
) -> list[BaseException]:
    """Délivre à Commandes chaque payment.refunded de la séance rangé dans l'outbox de
    Paiements, comme le ferait le relais ; rend les exceptions des traitements."""
    erreurs: list[BaseException] = []
    for ligne in await bases.paiements.lignes(
        "SELECT * FROM outbox WHERE type = 'ticketing.payment.refunded'"
    ):
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
        erreur = await traiter(sessions_commandes, evenement)
        if erreur is not None:
            erreurs.append(erreur)
    return erreurs


async def test_l_annulation_rembourse_la_commande_payee_et_expire_la_commande_en_attente_de_bout_en_bout(  # noqa: E501 : nom explicite
    plateforme: Any, bases: Any, sessions_commandes: Any, sessions_paiements: Any, outils: Any
) -> None:
    """Bout en bout Commandes ↔ Paiements (review BIL-011, point 4) : commande payée par
    `creerCommande` (vrai Paiements), commande `EN_ATTENTE`, puis `show.cancelled` traité par
    Commandes et Paiements, et chaque `payment.refunded` délivré deux fois à Commandes."""
    seance = await plateforme.nouvelle_seance()
    payee = outils.exiger_statut(
        await plateforme.commander("A", ["A1", "A2"], seance=seance), 201, "commande payée"
    )
    assert payee["statut"] == "CONFIRMEE"
    c2 = await bases.ajouter_commande(expire_le=echeance(), seance_id=seance.id, places=1)
    annulation = show_cancelled(seance.id)

    erreurs = [e for e in [await traiter(sessions_commandes, annulation)] if e is not None]
    await traiter_une_fois(
        sessions_paiements,
        "paiements.show-cancelled",
        rembourser_paiements_de_la_seance,
        annulation,
    )
    erreurs += await delivrer_remboursements(bases, sessions_commandes, seance.id)
    erreurs += await delivrer_remboursements(bases, sessions_commandes, seance.id)

    assert await bases.statut(payee["id"]) == "REMBOURSEE"
    lue = outils.exiger_statut(await plateforme.lire("A", payee["id"]), 200, "lireCommande")
    assert lue["statut"] == "REMBOURSEE"
    paiements = await bases.paiements_de(payee["id"])
    assert [(p["statut"], p["montant"]) for p in paiements] == [("REMBOURSE", 9000)]
    rembourses = [
        ligne
        for ligne in await bases.paiements.lignes(
            "SELECT * FROM outbox WHERE type = 'ticketing.payment.refunded'"
        )
        if ligne["data"]["commande_id"] == payee["id"]
    ]
    assert [r["data"]["montant"] for r in rembourses] == [9000], rembourses
    assert await bases.statut(c2.id) == "EXPIREE"
    expirees = await bases.evenements_de(EXPIREE, str(c2.id))
    assert len(expirees) == 1, expirees
    assert not expirees[0]["data"].get("remboursement_du"), expirees[0]["data"]
    assert await bases.evenements_de(EXPIREE, payee["id"]) == []
    assert erreurs == [], erreurs


async def test_un_paiement_rembourse_rejoue_par_payer_commande_finit_rembourse_sans_debit(
    plateforme: Any, bases: Any, sessions_commandes: Any, sessions_paiements: Any, outils: Any
) -> None:
    """Review BIL-011, point 4 : le paiement de C2 est accepté par Paiements (réponse perdue
    pour Commandes), remboursé par `show.cancelled` de Paiements, puis rejoué par
    `payerCommande` (201 `REMBOURSE`). Une fois `show.cancelled` et `payment.refunded` délivrés
    à Commandes, jamais de commande `CONFIRMEE` ni de paiement `ACCEPTE`."""
    seance = await plateforme.nouvelle_seance()
    c2 = await bases.ajouter_commande(
        expire_le=echeance(),
        seance_id=seance.id,
        place_ids=[seance.places["B1"]],
        client=outils.clients["B"]["sujet"],
        paiement_demande=True,
    )
    await plateforme.redis.poser(plateforme.cle_redis("B1", seance), str(c2.id), 600_000)
    accepte = await plateforme.paiements.post(
        "/api/v1/payments",
        json={
            "commande_id": str(c2.id),
            "seance_id": str(seance.id),
            "montant": 4500,
            "carte_test": "4242424242424242",
        },
        headers={"Idempotency-Key": str(c2.id)},
    )
    outils.exiger_statut(accepte, 201, "paiement accepté, réponse perdue pour Commandes")
    annulation = show_cancelled(seance.id)
    await traiter_une_fois(
        sessions_paiements,
        "paiements.show-cancelled",
        rembourser_paiements_de_la_seance,
        annulation,
    )

    rejeu = await plateforme.payer("B", str(c2.id))
    erreurs = [e for e in [await traiter(sessions_commandes, annulation)] if e is not None]
    erreurs += await delivrer_remboursements(bases, sessions_commandes, seance.id)

    assert rejeu.status_code < 500, rejeu.text
    statut = await bases.statut(c2.id)
    paiements = [p["statut"] for p in await bases.paiements_de(c2.id)]
    assert statut in ("REMBOURSEE", "EXPIREE"), f"commande {statut}, rejeu {rejeu.text}"
    assert paiements == ["REMBOURSE"], paiements
    assert erreurs == [], erreurs
