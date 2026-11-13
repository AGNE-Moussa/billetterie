"""BIL-009, CA1, CA2, CA3, E1, E4 : émission des billets à la réception de
ticketing.order.confirmed (plan docs/test-plans/BIL-009.md).

Le traitement d'une livraison, `billets.consommateurs.recevoir_commande_confirmee`
(transaction idempotente `messages_traites`, puis suppression des verrous de la commande), est
appelé directement sur la vraie base migrée et le vrai Redis du module (`VerrousRedis`) ; la
livraison par RabbitMQ est couverte par test_emission_rabbitmq.py.

Données du plan : séance `S` (places A1 à A4, parmi celles de la séance commune du conftest),
commande `C1` (A1 et A2, `client-test`), commande `C2` (A1, `client-b-test`). Clé QR :
`QR_CLE_SIGNATURE`, tirée au hasard pour chaque test.
"""

import json
import logging
import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from billets.consommateurs import recevoir_commande_confirmee
from billets.domaine.qr import verifier_qr
from billets.infra.verrous import VerrousRedis
from commun.evenements import Evenement

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[4]
SCHEMAS = RACINE / "docs" / "evenements"
CORRELATION = "correlation-bil-009-1"
CONSOMMATEUR = "billets.order-confirmed"
BILLET_EMIS = "ticketing.ticket.issued"
BILLETS_REFUSES = "ticketing.ticket.rejected"
DELAI_REDIS = 0.5
DUREE_VERROU_MS = 3_600_000


# --- Fixtures ---------------------------------------------------------------------------------


@pytest.fixture
def cle_qr(monkeypatch: pytest.MonkeyPatch) -> str:
    cle = secrets.token_urlsafe(32)
    monkeypatch.setenv("QR_CLE_SIGNATURE", cle)
    return cle


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    moteur = create_async_engine(database_url, connect_args={"timeout": 30, "command_timeout": 30})
    try:
        yield async_sessionmaker(moteur, expire_on_commit=False)
    finally:
        await moteur.dispose()


@pytest.fixture
async def verrous(redis_url: str) -> AsyncIterator[VerrousRedis]:
    magasin = VerrousRedis(redis_url, DELAI_REDIS)
    try:
        yield magasin
    finally:
        await magasin.fermer()


# --- Données et outils ------------------------------------------------------------------------


def commande(
    seance: Any,
    libelles: list[str],
    *,
    client: str = "client-test",
    email: str | None = "client.test@exemple.test",
) -> dict[str, Any]:
    """`data` de ticketing.order.confirmed (docs/evenements), lignes à 4500 centimes."""
    return {
        "commande_id": str(uuid.uuid4()),
        "client": client,
        "email": email,
        "seance_id": str(seance.id),
        "lignes": [{"place_id": str(seance.places[x]), "montant": 4500} for x in libelles],
        "montant_total": 4500 * len(libelles),
    }


def c1(seance: Any) -> dict[str, Any]:
    return commande(seance, ["A1", "A2"])


def c2(seance: Any) -> dict[str, Any]:
    return commande(seance, ["A1"], client="client-b-test", email="client.b.test@exemple.test")


def order_confirmed(data: dict[str, Any], identifiant: uuid.UUID | None = None) -> Evenement:
    return Evenement(
        id=identifiant or uuid.uuid4(),
        type="ticketing.order.confirmed",
        version=1,
        correlation_id=CORRELATION,
        data=data,
    )


async def traiter(
    sessions: async_sessionmaker[AsyncSession], verrous: VerrousRedis, evenement: Evenement
) -> BaseException | None:
    """Une livraison ; rend l'exception levée (ou None) pour vérifier d'abord l'état."""
    try:
        await recevoir_commande_confirmee(sessions, verrous, evenement)
    except Exception as erreur:  # noqa: BLE001 : classée par le test
        return erreur
    return None


async def billets_de(base: Any, data: dict[str, Any]) -> list[Any]:
    return await base.lignes(  # type: ignore[no-any-return]
        "SELECT xmin::text AS xmin, * FROM billets WHERE commande_id = :commande",
        commande=uuid.UUID(data["commande_id"]),
    )


async def outbox(base: Any, type_evenement: str) -> list[Any]:
    return await base.lignes(  # type: ignore[no-any-return]
        "SELECT xmin::text AS xmin, * FROM outbox WHERE type = :type ORDER BY cree_le",
        type=type_evenement,
    )


async def traites(base: Any, message_id: uuid.UUID | None = None) -> list[Any]:
    requete = "SELECT xmin::text AS xmin, * FROM messages_traites WHERE consommateur = :nom"
    if message_id is None:
        return await base.lignes(requete, nom=CONSOMMATEUR)  # type: ignore[no-any-return]
    return await base.lignes(  # type: ignore[no-any-return]
        requete + " AND message_id = :message", nom=CONSOMMATEUR, message=message_id
    )


async def inserer_billet_de(base: Any, data: dict[str, Any], place_id: uuid.UUID) -> uuid.UUID:
    """Billet `EMIS` d'une commande (C2), inséré directement."""
    billet_id = uuid.uuid4()
    await base.executer(
        "INSERT INTO billets (id, commande_id, client, seance_id, place_id, statut, qr_code,"
        " emis_le) VALUES (:id, :commande_id, :client, :seance_id, :place_id, 'EMIS',"
        " :qr_code, :emis_le)",
        id=billet_id,
        commande_id=uuid.UUID(data["commande_id"]),
        client=data["client"],
        seance_id=uuid.UUID(data["seance_id"]),
        place_id=place_id,
        qr_code=f"qr-de-test-{billet_id}",
        emis_le=datetime.now(UTC),
    )
    return billet_id


async def annuler_seance(base: Any, seance_id: uuid.UUID) -> None:
    await base.executer(
        "INSERT INTO seances_annulees (seance_id, annulee_le) VALUES (:seance, :le)",
        seance=seance_id,
        le=datetime.now(UTC),
    )


def enveloppe(ligne: Any) -> dict[str, Any]:
    """Ligne `outbox` remise dans l'enveloppe commun.evenements.Evenement."""
    return {
        "id": str(ligne["id"]),
        "type": ligne["type"],
        "version": ligne["version"],
        "occurred_at": ligne["occurred_at"].isoformat(),
        "correlation_id": ligne["correlation_id"],
        "data": ligne["data"],
    }


def erreurs_schema(document: dict[str, Any], type_evenement: str) -> list[str]:
    schema = json.loads((SCHEMAS / f"{type_evenement}.json").read_text(encoding="utf-8"))
    validateur = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    return [f"{list(e.absolute_path)} : {e.message}" for e in validateur.iter_errors(document)]


# --- CA1 --------------------------------------------------------------------------------------


async def test_order_confirmed_emet_un_billet_emis_par_place_et_rend_les_places_indisponibles(
    plateforme: Any, seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    data = c1(seance)

    erreur = await traiter(sessions, verrous, order_confirmed(data))

    billets = await billets_de(base, data)
    assert len(billets) == 2, f"{len(billets)} billets au lieu de 2"
    assert {b["place_id"] for b in billets} == {seance.places["A1"], seance.places["A2"]}
    assert len({b["id"] for b in billets}) == 2
    for billet in billets:
        assert billet["statut"] == "EMIS"
        assert billet["client"] == "client-test"
        assert billet["seance_id"] == seance.id
        assert billet["qr_code"]
        assert billet["emis_le"].tzinfo is not None
    disponibles = await plateforme.disponibilites(seance.id)
    assert disponibles[str(seance.places["A1"])] is False
    assert disponibles[str(seance.places["A2"])] is False
    assert disponibles[str(seance.places["A3"])] is True
    assert disponibles[str(seance.places["A4"])] is True
    assert erreur is None


async def test_les_billets_et_leurs_ticket_issued_sont_ecrits_dans_la_meme_transaction(
    seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    data = c1(seance)
    message = order_confirmed(data)

    await traiter(sessions, verrous, message)

    billets = await billets_de(base, data)
    emis = await outbox(base, BILLET_EMIS)
    assert len(emis) == 2, f"{len(emis)} ticket.issued au lieu de 2"
    assert sorted(e["data"]["billet_id"] for e in emis) == sorted(str(b["id"]) for b in billets)
    traite = await traites(base, message.id)
    assert len(traite) == 1
    transactions = {b["xmin"] for b in billets} | {e["xmin"] for e in emis} | {traite[0]["xmin"]}
    assert len(transactions) == 1, f"écritures dans plusieurs transactions : {transactions}"
    assert await outbox(base, BILLETS_REFUSES) == []


async def test_ticket_issued_respecte_son_schema_v1(
    seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    data = c1(seance)

    await traiter(sessions, verrous, order_confirmed(data))

    emis = await outbox(base, BILLET_EMIS)
    assert len(emis) == 2, f"{len(emis)} ticket.issued au lieu de 2"
    billets = {str(b["id"]): b for b in await billets_de(base, data)}
    for ligne in emis:
        document = enveloppe(ligne)
        assert erreurs_schema(document, BILLET_EMIS) == []
        assert "email" not in ligne["data"]
        assert ligne["correlation_id"] == CORRELATION
        billet = billets[ligne["data"]["billet_id"]]
        assert ligne["data"]["commande_id"] == str(billet["commande_id"])
        assert ligne["data"]["seance_id"] == str(billet["seance_id"])
        assert ligne["data"]["place_id"] == str(billet["place_id"])
        assert ligne["data"]["qr_code"] == billet["qr_code"]
        assert datetime.fromisoformat(ligne["data"]["emis_le"]) == billet["emis_le"]


# --- CA2 --------------------------------------------------------------------------------------


async def test_le_qr_enregistre_et_publie_est_verifiable_par_billets(
    seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    data = c1(seance)

    await traiter(sessions, verrous, order_confirmed(data))

    emis = {e["data"]["billet_id"]: e["data"] for e in await outbox(base, BILLET_EMIS)}
    billets = await billets_de(base, data)
    assert len(billets) == 2, f"{len(billets)} billets au lieu de 2"
    for billet in billets:
        assert emis[str(billet["id"])]["qr_code"] == billet["qr_code"]
        assert verifier_qr(billet["qr_code"], cle=cle_qr) == billet["id"]


# --- CA3 --------------------------------------------------------------------------------------


async def test_order_confirmed_rejoue_n_emet_ni_second_billet_ni_second_ticket_issued(
    seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    data = c1(seance)
    message = order_confirmed(data)

    erreurs = [await traiter(sessions, verrous, message) for _ in range(2)]

    assert len(await billets_de(base, data)) == 2
    assert len(await outbox(base, BILLET_EMIS)) == 2
    assert len(await traites(base)) == 1
    assert erreurs == [None, None]


async def test_order_confirmed_republie_sous_un_autre_identifiant_n_emet_rien_de_plus(
    seance: Any,
    base: Any,
    sessions: Any,
    verrous: Any,
    cle_qr: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    data = c1(seance)
    premiere = await traiter(sessions, verrous, order_confirmed(data))
    assert len(await billets_de(base, data)) == 2, "première livraison : billets absents"

    seconde = await traiter(sessions, verrous, order_confirmed(data))

    assert len(await billets_de(base, data)) == 2
    assert len(await outbox(base, BILLET_EMIS)) == 2
    assert await outbox(base, BILLETS_REFUSES) == []
    erreurs = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert erreurs == []
    assert (premiere, seconde) == (None, None)


async def test_une_commande_deja_emise_republiee_apres_annulation_de_la_seance_ne_publie_pas_de_ticket_rejected(  # noqa: E501
    seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    data = c1(seance)
    premiere = await traiter(sessions, verrous, order_confirmed(data))
    assert len(await billets_de(base, data)) == 2, "première livraison : billets absents"
    assert len(await outbox(base, BILLET_EMIS)) == 2, "première livraison : ticket.issued absents"
    await annuler_seance(base, seance.id)

    seconde = await traiter(sessions, verrous, order_confirmed(data, uuid.uuid4()))

    assert len(await billets_de(base, data)) == 2
    assert await outbox(base, BILLETS_REFUSES) == []
    assert len(await outbox(base, BILLET_EMIS)) == 2
    assert (premiere, seconde) == (None, None)


# --- E1 : refus d'émission --------------------------------------------------------------------


async def test_une_place_deja_vendue_n_emet_aucun_billet_de_la_commande_et_publie_ticket_rejected(
    seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    data_c1, data_c2 = c1(seance), c2(seance)
    billet_c2 = await inserer_billet_de(base, data_c2, seance.places["A1"])
    message = order_confirmed(data_c1)

    erreur = await traiter(sessions, verrous, message)

    refus = await outbox(base, BILLETS_REFUSES)
    assert [r["data"] for r in refus] == [
        {
            "commande_id": data_c1["commande_id"],
            "seance_id": str(seance.id),
            "place_ids": [str(seance.places["A1"])],
            "motif": "PLACE_DEJA_VENDUE",
        }
    ]
    assert await billets_de(base, data_c1) == []
    assert [b["id"] for b in await billets_de(base, data_c2)] == [billet_c2]
    assert await outbox(base, BILLET_EMIS) == []
    assert len(await traites(base, message.id)) == 1
    assert erreur is None


async def test_une_seance_annulee_n_emet_aucun_billet_et_publie_ticket_rejected(
    seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    await annuler_seance(base, seance.id)
    data = c1(seance)

    erreur = await traiter(sessions, verrous, order_confirmed(data))

    refus = await outbox(base, BILLETS_REFUSES)
    assert len(refus) == 1, f"{len(refus)} ticket.rejected au lieu de 1"
    assert refus[0]["data"]["motif"] == "SEANCE_ANNULEE"
    assert refus[0]["data"]["commande_id"] == data["commande_id"]
    assert sorted(refus[0]["data"]["place_ids"]) == sorted(
        [str(seance.places["A1"]), str(seance.places["A2"])]
    )
    assert await billets_de(base, data) == []
    assert await outbox(base, BILLET_EMIS) == []
    assert erreur is None


@pytest.mark.parametrize("motif", ["PLACE_DEJA_VENDUE", "SEANCE_ANNULEE"])
async def test_ticket_rejected_respecte_son_schema_et_suit_la_transaction_du_message(
    motif: str, seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    if motif == "PLACE_DEJA_VENDUE":
        await inserer_billet_de(base, c2(seance), seance.places["A1"])
    else:
        await annuler_seance(base, seance.id)
    message = order_confirmed(c1(seance))

    await traiter(sessions, verrous, message)

    refus = await outbox(base, BILLETS_REFUSES)
    assert len(refus) == 1, f"{len(refus)} ticket.rejected au lieu de 1"
    assert erreurs_schema(enveloppe(refus[0]), BILLETS_REFUSES) == []
    assert refus[0]["data"]["motif"] == motif
    assert refus[0]["correlation_id"] == CORRELATION
    traite = await traites(base, message.id)
    assert len(traite) == 1
    assert refus[0]["xmin"] == traite[0]["xmin"]


async def test_order_confirmed_rejete_puis_rejoue_ne_publie_qu_un_ticket_rejected(
    seance: Any, base: Any, sessions: Any, verrous: Any, cle_qr: str
) -> None:
    data = c1(seance)
    await inserer_billet_de(base, c2(seance), seance.places["A1"])
    message = order_confirmed(data)

    erreurs = [await traiter(sessions, verrous, message) for _ in range(2)]

    assert len(await outbox(base, BILLETS_REFUSES)) == 1
    assert await billets_de(base, data) == []
    assert erreurs == [None, None]


# --- E4 : verrous Redis après l'émission ou le rejet ------------------------------------------


async def test_les_verrous_de_la_commande_sont_supprimes_apres_l_emission(
    plateforme: Any,
    seance: Any,
    base: Any,
    observateur: Any,
    sessions: Any,
    verrous: Any,
    outils: Any,
    cle_qr: str,
) -> None:
    data = c1(seance)
    cles = [outils.cle_verrou(seance.id, seance.places[x]) for x in ("A1", "A2")]
    for cle in cles:
        await observateur.poser(cle, data["commande_id"], DUREE_VERROU_MS)

    erreur = await traiter(sessions, verrous, order_confirmed(data))

    assert [await observateur.valeur(cle) for cle in cles] == [None, None]
    disponibles = await plateforme.disponibilites(seance.id)
    assert disponibles[str(seance.places["A1"])] is False
    assert disponibles[str(seance.places["A2"])] is False
    assert erreur is None


async def test_les_verrous_de_la_commande_sont_supprimes_apres_un_rejet(
    seance: Any,
    base: Any,
    observateur: Any,
    sessions: Any,
    verrous: Any,
    outils: Any,
    cle_qr: str,
) -> None:
    data = c1(seance)
    await inserer_billet_de(base, c2(seance), seance.places["A1"])
    cle_a2 = outils.cle_verrou(seance.id, seance.places["A2"])
    await observateur.poser(cle_a2, data["commande_id"], DUREE_VERROU_MS)

    erreur = await traiter(sessions, verrous, order_confirmed(data))

    assert await observateur.valeur(cle_a2) is None
    assert len(await outbox(base, BILLETS_REFUSES)) == 1
    assert erreur is None


async def test_un_verrou_tenu_par_une_autre_commande_n_est_pas_supprime(
    seance: Any,
    base: Any,
    observateur: Any,
    sessions: Any,
    verrous: Any,
    outils: Any,
    cle_qr: str,
) -> None:
    data_c1, data_c2 = c1(seance), c2(seance)
    cle_a2 = outils.cle_verrou(seance.id, seance.places["A2"])
    await observateur.poser(cle_a2, data_c2["commande_id"], DUREE_VERROU_MS)
    message = order_confirmed(data_c1)

    erreur = await traiter(sessions, verrous, message)

    assert len(await traites(base, message.id)) == 1, "C1 non traité"
    assert await observateur.valeur(cle_a2) == data_c2["commande_id"]
    pttl = await observateur.pttl(cle_a2)
    assert 0 < pttl <= DUREE_VERROU_MS, f"PTTL {pttl}"
    assert erreur is None


async def test_redis_injoignable_apres_emission_garde_les_billets_emis(
    seance: Any,
    base: Any,
    redis: Any,
    sessions: Any,
    verrous: Any,
    outils: Any,
    cle_qr: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    data = c1(seance)
    message = order_confirmed(data)
    conteneur = redis.get_wrapped_container()

    conteneur.pause()
    try:
        erreur = await outils.borne(
            "traitement, Redis en pause", traiter(sessions, verrous, message)
        )
    finally:
        conteneur.unpause()

    assert len(await billets_de(base, data)) == 2
    assert len(await outbox(base, BILLET_EMIS)) == 2
    assert len(await traites(base, message.id)) == 1
    avertissements = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert avertissements, "aucun journal WARNING pour la suppression des verrous en échec"
    assert erreur is None
