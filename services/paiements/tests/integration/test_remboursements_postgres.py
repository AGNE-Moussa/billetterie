"""BIL-011, CA1 : remboursements de Paiements à `ticketing.show.cancelled` et
`ticketing.ticket.rejected` (plan docs/test-plans/BIL-011.md, Q1, H5, H6).

Le traitement d'une livraison (`commun.consommateurs.traiter_une_fois` avec les traitements de
`paiements.consommateurs`, files `paiements.show-cancelled` et `paiements.ticket-rejected`) est
appelé directement sur la vraie base migrée ; une exception remontée signifierait un nouvel
essai, puis la DLQ. Paiements `ACCEPTE` créés par `POST /api/v1/payments` (carte de test
acceptée de BIL-008) ; paiements `REFUSE` ou `REMBOURSE` insérés en base.
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from commun.consommateurs import traiter_une_fois
from commun.evenements import Evenement
from paiements.consommateurs import (
    rembourser_paiement_de_la_commande,
    rembourser_paiements_de_la_seance,
)

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[4]
SCHEMA_REMBOURSEMENT = json.loads(
    (RACINE / "docs" / "evenements" / "ticketing.payment.refunded.json").read_text(encoding="utf-8")
)
CORRELATION = "correlation-bil-011-1"
CONSOMMATEUR_SEANCE = "paiements.show-cancelled"
CONSOMMATEUR_REFUS = "paiements.ticket-rejected"
REMBOURSE = "ticketing.payment.refunded"


# --- Fixtures et outils -----------------------------------------------------------------------


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    moteur = create_async_engine(database_url, connect_args={"timeout": 30, "command_timeout": 30})
    try:
        yield async_sessionmaker(moteur, expire_on_commit=False)
    finally:
        await moteur.dispose()


def show_cancelled(seance_id: uuid.UUID, identifiant: Any = None) -> Evenement:
    return Evenement(
        id=identifiant or uuid.uuid4(),
        type="ticketing.show.cancelled",
        correlation_id=CORRELATION,
        data={"seance_id": str(seance_id), "evenement_id": str(uuid.uuid4())},
    )


def ticket_rejected(commande_id: uuid.UUID, seance_id: uuid.UUID, motif: str) -> Evenement:
    return Evenement(
        type="ticketing.ticket.rejected",
        correlation_id=CORRELATION,
        data={
            "commande_id": str(commande_id),
            "seance_id": str(seance_id),
            "place_ids": [str(uuid.uuid4())],
            "motif": motif,
        },
    )


async def traiter(sessions: Any, evenement: Evenement) -> BaseException | None:
    """Une livraison, routée vers le traitement de son type ; rend l'exception (ou None)."""
    if evenement.type == "ticketing.show.cancelled":
        nom, traitement = CONSOMMATEUR_SEANCE, rembourser_paiements_de_la_seance
    else:
        nom, traitement = CONSOMMATEUR_REFUS, rembourser_paiement_de_la_commande
    try:
        await traiter_une_fois(sessions, nom, traitement, evenement)
    except Exception as erreur:  # noqa: BLE001 : classée par le test
        return erreur
    return None


async def payer(
    service: Any, outils: Any, commande_id: uuid.UUID, seance_id: uuid.UUID, montant: int
) -> dict[str, Any]:
    reponse = await service.payer(commande_id=commande_id, seance_id=seance_id, montant=montant)
    return outils.exiger_statut(reponse, 201, f"paiement préalable de {commande_id}")  # type: ignore[no-any-return]


async def inserer(
    base: Any, commande_id: uuid.UUID, seance_id: uuid.UUID, statut: str
) -> uuid.UUID:
    paiement_id = uuid.uuid4()
    await base.executer(
        "INSERT INTO paiements (id, commande_id, seance_id, montant, statut, cree_le)"
        " VALUES (:id, :commande_id, :seance_id, 4500, :statut, :le)",
        id=paiement_id,
        commande_id=commande_id,
        seance_id=seance_id,
        statut=statut,
        le=datetime.now(UTC),
    )
    return paiement_id


async def statut(base: Any, paiement_id: Any) -> str:
    lignes = await base.lignes(
        "SELECT statut FROM paiements WHERE id = :id", id=uuid.UUID(str(paiement_id))
    )
    assert len(lignes) == 1, lignes
    return str(lignes[0]["statut"])


async def remboursements(base: Any, paiement_id: Any = None) -> list[dict[str, Any]]:
    lignes = await base.lignes(
        "SELECT xmin::text AS xmin, * FROM outbox WHERE type = :t", t=REMBOURSE
    )
    if paiement_id is None:
        return lignes  # type: ignore[no-any-return]
    return [ligne for ligne in lignes if ligne["data"].get("paiement_id") == str(paiement_id)]


async def traite(base: Any, nom: str, message_id: uuid.UUID) -> int:
    lignes = await base.lignes(
        "SELECT count(*) AS n FROM messages_traites WHERE consommateur = :c AND message_id = :m",
        c=nom,
        m=message_id,
    )
    return int(lignes[0]["n"])


def erreurs_evenement(ligne: dict[str, Any]) -> list[str]:
    enveloppe = {
        "id": str(ligne["id"]),
        "type": ligne["type"],
        "version": ligne["version"],
        "occurred_at": ligne["occurred_at"].isoformat(),
        "correlation_id": ligne["correlation_id"],
        "data": ligne["data"],
    }
    validateur = Draft202012Validator(
        SCHEMA_REMBOURSEMENT, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    return [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(enveloppe)]


# --- show.cancelled ---------------------------------------------------------------------------


async def test_les_paiements_de_la_seance_sont_rembourses_en_base(
    service: Any, base: Any, sessions: Any, outils: Any
) -> None:
    s, s2 = uuid.uuid4(), uuid.uuid4()
    c1, c3 = uuid.uuid4(), uuid.uuid4()
    p1 = await payer(service, outils, c1, s, 9000)
    p3 = await payer(service, outils, c3, s, 4500)
    refuse = await inserer(base, uuid.uuid4(), s, "REFUSE")
    p4 = await payer(service, outils, uuid.uuid4(), s2, 4500)
    message = show_cancelled(s)

    erreur = await traiter(sessions, message)

    assert len(await base.lignes("SELECT * FROM seances_annulees WHERE seance_id = :s", s=s)) == 1
    assert await statut(base, p1["id"]) == "REMBOURSE"
    assert await statut(base, p3["id"]) == "REMBOURSE"
    assert await statut(base, refuse) == "REFUSE"
    assert await statut(base, p4["id"]) == "ACCEPTE"
    publies = await remboursements(base)
    assert len(publies) == 2, publies
    attendus = {
        p1["id"]: {
            "paiement_id": p1["id"],
            "commande_id": str(c1),
            "seance_id": str(s),
            "montant": 9000,
        },
        p3["id"]: {
            "paiement_id": p3["id"],
            "commande_id": str(c3),
            "seance_id": str(s),
            "montant": 4500,
        },
    }
    xmins = {
        str(ligne["id"]): ligne["xmin"]
        for ligne in await base.lignes("SELECT xmin::text AS xmin, id FROM paiements")
    }
    for ligne in publies:
        paiement_id = ligne["data"]["paiement_id"]
        assert ligne["data"] == attendus[paiement_id]
        assert erreurs_evenement(ligne) == []
        # Même transaction que le passage REMBOURSE du paiement.
        assert ligne["xmin"] == xmins[paiement_id]
    assert await traite(base, CONSOMMATEUR_SEANCE, message.id) == 1
    assert erreur is None, repr(erreur)


async def test_show_cancelled_recu_deux_fois_ne_rembourse_qu_une_fois(
    service: Any, base: Any, sessions: Any, outils: Any
) -> None:
    s = uuid.uuid4()
    p1 = await payer(service, outils, uuid.uuid4(), s, 9000)
    message = show_cancelled(s)

    erreurs = [await traiter(sessions, message), await traiter(sessions, message)]
    erreurs.append(await traiter(sessions, show_cancelled(s)))

    assert await statut(base, p1["id"]) == "REMBOURSE"
    assert len(await remboursements(base, p1["id"])) == 1
    assert len(await remboursements(base)) == 1
    assert [e for e in erreurs if e is not None] == []


# --- ticket.rejected (Q1) ---------------------------------------------------------------------


@pytest.mark.parametrize("motif", ["PLACE_DEJA_VENDUE", "SEANCE_ANNULEE"])
async def test_ticket_rejected_rembourse_le_paiement_de_la_commande(
    motif: str, service: Any, base: Any, sessions: Any, outils: Any
) -> None:
    s, c1 = uuid.uuid4(), uuid.uuid4()
    p1 = await payer(service, outils, c1, s, 9000)

    erreur = await traiter(sessions, ticket_rejected(c1, s, motif))

    assert await statut(base, p1["id"]) == "REMBOURSE"
    publies = await remboursements(base, p1["id"])
    assert [p["data"]["commande_id"] for p in publies] == [str(c1)], publies
    assert len(await remboursements(base)) == 1
    assert erreur is None, repr(erreur)


@pytest.mark.parametrize("paiement", ["REFUSE", "REMBOURSE", "absent"])
async def test_ticket_rejected_sans_paiement_accepte_ne_rembourse_rien(
    paiement: str, base: Any, sessions: Any
) -> None:
    s, c1 = uuid.uuid4(), uuid.uuid4()
    paiement_id = None if paiement == "absent" else await inserer(base, c1, s, paiement)
    message = ticket_rejected(c1, s, "PLACE_DEJA_VENDUE")

    erreur = await traiter(sessions, message)

    if paiement_id is not None:
        assert await statut(base, paiement_id) == paiement
    else:
        assert await base.paiements() == []
    assert await remboursements(base) == []
    assert await traite(base, CONSOMMATEUR_REFUS, message.id) == 1
    assert erreur is None, repr(erreur)


@pytest.mark.parametrize("ordre", ["show_cancelled_d_abord", "ticket_rejected_d_abord"])
async def test_show_cancelled_puis_ticket_rejected_sur_la_meme_commande_ne_remboursent_qu_une_fois(  # noqa: E501 : nom du plan
    ordre: str, service: Any, base: Any, sessions: Any, outils: Any
) -> None:
    s, c1 = uuid.uuid4(), uuid.uuid4()
    p1 = await payer(service, outils, c1, s, 9000)
    messages = [show_cancelled(s), ticket_rejected(c1, s, "SEANCE_ANNULEE")]
    if ordre == "ticket_rejected_d_abord":
        messages.reverse()

    erreurs = [await traiter(sessions, message) for message in messages]

    assert await statut(base, p1["id"]) == "REMBOURSE"
    assert len(await remboursements(base, p1["id"])) == 1
    assert [e for e in erreurs if e is not None] == []


# --- creerPaiement après l'annulation ---------------------------------------------------------


async def test_un_paiement_demande_apres_l_annulation_renvoie_409_show_cancelled(
    service: Any, base: Any, sessions: Any, outils: Any
) -> None:
    s = uuid.uuid4()
    erreur = await traiter(sessions, show_cancelled(s))

    reponse = await service.payer(commande_id=uuid.uuid4(), seance_id=s, montant=4500)

    outils.exiger_probleme(reponse, 409, "SHOW_CANCELLED", "paiement après show.cancelled")
    assert await base.paiements() == []
    assert erreur is None, repr(erreur)


async def test_un_paiement_accepte_rejoue_apres_annulation_renvoie_le_paiement_enregistre(
    service: Any, base: Any, sessions: Any, outils: Any
) -> None:
    s, c1 = uuid.uuid4(), uuid.uuid4()
    cle = str(c1)  # Idempotency-Key = commande_id (contrat de creerPaiement)
    premier = await service.payer(commande_id=c1, seance_id=s, montant=9000, cle=cle)
    p1 = outils.exiger_statut(premier, 201, "premier paiement")
    erreur = await traiter(sessions, show_cancelled(s))

    rejeu = await service.payer(commande_id=c1, seance_id=s, montant=9000, cle=cle)

    corps = outils.exiger_statut(rejeu, 201, "rejeu après annulation")
    assert corps["id"] == p1["id"]
    assert corps["statut"] == "REMBOURSE"
    assert len(await base.paiements()) == 1
    assert len(await remboursements(base, p1["id"])) == 1
    assert erreur is None, repr(erreur)
