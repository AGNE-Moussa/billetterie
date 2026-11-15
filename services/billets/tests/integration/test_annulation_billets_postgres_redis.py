"""BIL-011, CA3 : `ticketing.show.cancelled` invalide les billets de la séance (plan
docs/test-plans/BIL-011.md, H4, H5, Q3).

Le traitement d'une livraison (`commun.consommateurs.traiter_une_fois` avec
`billets.consommateurs.annuler_billets_de_la_seance`, file `billets.show-cancelled`) est appelé
directement sur la vraie base migrée et le vrai Redis du module ; une exception remontée
signifierait un nouvel essai, puis la DLQ. Billets synthétiques insérés en base (`EMIS`).
"""

import secrets
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from billets.consommateurs import annuler_billets_de_la_seance, recevoir_commande_confirmee
from billets.infra.verrous import VerrousRedis
from commun.consommateurs import traiter_une_fois
from commun.evenements import Evenement

pytestmark = pytest.mark.anyio

CONSOMMATEUR = "billets.show-cancelled"
CORRELATION = "correlation-bil-011-1"
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
async def verrous(redis_url: str, observateur: Any) -> AsyncIterator[VerrousRedis]:
    magasin = VerrousRedis(redis_url, DELAI_REDIS)
    try:
        yield magasin
    finally:
        await magasin.fermer()


# --- Données et outils ------------------------------------------------------------------------


def show_cancelled(
    seance_id: uuid.UUID, evenement_id: uuid.UUID, identifiant: Any = None
) -> Evenement:
    return Evenement(
        id=identifiant or uuid.uuid4(),
        type="ticketing.show.cancelled",
        version=1,
        correlation_id=CORRELATION,
        data={"seance_id": str(seance_id), "evenement_id": str(evenement_id)},
    )


def order_confirmed(seance: Any, libelles: list[str], client: str, email: str) -> Evenement:
    return Evenement(
        type="ticketing.order.confirmed",
        version=1,
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


async def annuler(
    sessions: async_sessionmaker[AsyncSession], evenement: Evenement
) -> BaseException | None:
    """Une livraison de show.cancelled ; rend l'exception levée (ou None)."""
    try:
        await traiter_une_fois(sessions, CONSOMMATEUR, annuler_billets_de_la_seance, evenement)
    except Exception as erreur:  # noqa: BLE001 : classée par le test
        return erreur
    return None


async def confirmer(
    sessions: async_sessionmaker[AsyncSession], verrous: VerrousRedis, evenement: Evenement
) -> BaseException | None:
    try:
        await recevoir_commande_confirmee(sessions, verrous, evenement)
    except Exception as erreur:  # noqa: BLE001 : classée par le test
        return erreur
    return None


async def seances_annulees(base: Any, seance_id: uuid.UUID) -> list[Any]:
    return await base.lignes(  # type: ignore[no-any-return]
        "SELECT * FROM seances_annulees WHERE seance_id = :s", s=seance_id
    )


async def billets_de_la_seance(base: Any, seance_id: uuid.UUID) -> list[Any]:
    return await base.lignes(  # type: ignore[no-any-return]
        "SELECT * FROM billets WHERE seance_id = :s ORDER BY id", s=seance_id
    )


async def traite(base: Any, message_id: uuid.UUID) -> int:
    lignes = await base.lignes(
        "SELECT count(*) AS n FROM messages_traites WHERE consommateur = :c AND message_id = :m",
        c=CONSOMMATEUR,
        m=message_id,
    )
    return int(lignes[0]["n"])


# --- CA3 --------------------------------------------------------------------------------------


async def test_les_billets_de_la_seance_passent_annule_en_base(
    base: Any, seance: Any, sessions: Any
) -> None:
    evenement_id = uuid.uuid4()
    s2 = await base.semer_seance()
    for libelle in ("A1", "A2", "A3"):  # C1 (A1, A2) et C3 (A3) sur S
        await base.inserer_billet(seance.id, seance.places[libelle])
    billet_c4 = await base.inserer_billet(s2.id, s2.places["A1"])
    avant = {ligne["id"]: ligne["qr_code"] for ligne in await billets_de_la_seance(base, seance.id)}
    message = show_cancelled(seance.id, evenement_id)

    erreur = await annuler(sessions, message)

    inscrites = await seances_annulees(base, seance.id)
    assert len(inscrites) == 1, inscrites
    assert inscrites[0]["annulee_le"] is not None
    billets = await billets_de_la_seance(base, seance.id)
    assert [b["statut"] for b in billets] == ["ANNULE"] * 3
    assert {b["id"]: b["qr_code"] for b in billets} == avant
    (c4,) = await billets_de_la_seance(base, s2.id)
    assert (c4["id"], c4["statut"]) == (billet_c4, "EMIS")
    assert await seances_annulees(base, s2.id) == []
    assert await traite(base, message.id) == 1
    assert erreur is None, repr(erreur)


async def test_une_seance_sans_billet_est_quand_meme_inscrite_annulee(
    base: Any, seance: Any, sessions: Any
) -> None:
    message = show_cancelled(seance.id, uuid.uuid4())

    erreur = await annuler(sessions, message)

    assert len(await seances_annulees(base, seance.id)) == 1
    assert await traite(base, message.id) == 1
    assert erreur is None, repr(erreur)


async def test_show_cancelled_recu_deux_fois_ne_change_rien_de_plus(
    base: Any, seance: Any, sessions: Any
) -> None:
    evenement_id = uuid.uuid4()
    await base.inserer_billet(seance.id, seance.places["A1"])
    message = show_cancelled(seance.id, evenement_id)

    erreurs = [await annuler(sessions, message)]
    premiere = await seances_annulees(base, seance.id)
    erreurs.append(await annuler(sessions, message))
    erreurs.append(await annuler(sessions, show_cancelled(seance.id, evenement_id)))

    assert len(premiere) == 1, premiere
    inscrites = await seances_annulees(base, seance.id)
    assert len(inscrites) == 1, inscrites
    assert inscrites[0]["annulee_le"] == premiere[0]["annulee_le"]
    assert [b["statut"] for b in await billets_de_la_seance(base, seance.id)] == ["ANNULE"]
    assert [e for e in erreurs if e is not None] == []


async def test_un_order_confirmed_apres_l_annulation_n_emet_aucun_billet(
    base: Any, seance: Any, sessions: Any, verrous: Any, observateur: Any, cle_qr: str, outils: Any
) -> None:
    c2 = order_confirmed(seance, ["B1"], "client-b-test", "client2.test@exemple.test")
    b1 = str(seance.places["B1"])
    cle = outils.cle_verrou(seance.id, b1)
    await observateur.poser(cle, c2.data["commande_id"], DUREE_VERROU_MS)

    erreur_annulation = await annuler(sessions, show_cancelled(seance.id, uuid.uuid4()))
    erreur_emission = await confirmer(sessions, verrous, c2)

    assert await billets_de_la_seance(base, seance.id) == []
    refus = [
        ligne
        for ligne in await base.lignes("SELECT * FROM outbox WHERE type = :t", t=BILLETS_REFUSES)
        if ligne["data"].get("commande_id") == c2.data["commande_id"]
    ]
    assert [(r["data"]["motif"], r["data"]["place_ids"]) for r in refus] == [
        ("SEANCE_ANNULEE", [b1])
    ]
    assert await observateur.valeur(cle) is None
    assert erreur_annulation is None, repr(erreur_annulation)
    assert erreur_emission is None, repr(erreur_emission)


async def test_l_annulation_ne_libere_aucune_place_occupee_par_un_billet_annule(
    base: Any, seance: Any, sessions: Any, plateforme: Any
) -> None:
    for libelle in ("A1", "A2"):  # billets de C1
        await base.inserer_billet(seance.id, seance.places[libelle])

    erreur = await annuler(sessions, show_cancelled(seance.id, uuid.uuid4()))

    assert [b["statut"] for b in await billets_de_la_seance(base, seance.id)] == ["ANNULE"] * 2
    assert erreur is None, repr(erreur)
    disponibles = await plateforme.disponibilites(seance.id)
    assert disponibles[str(seance.places["A1"])] is False
    assert disponibles[str(seance.places["A2"])] is False
    with pytest.raises(IntegrityError) as conflit:
        await base.inserer_billet(seance.id, seance.places["A1"])
    assert "uq_billets_place" in str(conflit.value)
