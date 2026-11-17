"""BIL-010, CA1 en concurrence : expiration pendant un `payerCommande`, même place disputée
après une expiration (plan docs/test-plans/BIL-010.md, hypothèse H3, décision Q6).

Vrais Commandes (deux instances), Billets et Paiements en ASGI, vraie base et vrai Redis
(fixture `plateforme_commandes`) ; un cycle de la tâche = `Plateforme.cycle()` (sessions et
client Paiements de l'instance, vrai verrou Redis). Marqueur `concurrence` (make
test-concurrence).
"""

import asyncio
import functools
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from billets.consommateurs import (
    liberer_places_de_la_commande_expiree,
    recevoir_commande_confirmee,
)
from billets.infra.verrous import VerrousRedis
from commandes.infra.clients import CIBLE_PAIEMENTS
from commun.consommateurs import traiter_une_fois
from commun.evenements import Evenement

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

EXPIREE = "ticketing.order.expired"
CONFIRMEE = "ticketing.order.confirmed"
CONSOMMATEUR_EXPIREE = "billets.order-expired"
DUREES_COURTES = {"duree_verrou_reservation": 2, "duree_verrou_confirmation": 2}
ATTENTE_EXPIRATION = 2.5
REPETITIONS = 20
# Places de la séance S pour les 20 répétitions (une commande neuve par répétition).
PLACES_REPETITIONS = [f"A{n}" for n in range(1, 11)] + [f"B{n}" for n in range(1, 11)]
CLIENTS_EN_CONCURRENCE = 10
DELAI_REDIS = 0.5
CLE_QR = "cle-de-test-" * 3


def client_de_test() -> dict[str, Any]:
    """Client synthétique `client-test-<uuid4>` (données communes du plan)."""
    return {
        "sujet": f"client-test-{uuid.uuid4()}",
        "roles": ["customer"],
        "scopes": ["orders:read", "orders:write"],
        "email": "client.test@exemple.test",
    }


@pytest.fixture
async def plateforme_courte(
    plateforme_commandes: Callable[..., AbstractAsyncContextManager[Any]],
) -> AsyncIterator[Any]:
    async with plateforme_commandes(billets=DUREES_COURTES) as demarree:
        yield demarree


async def commande_en_attente(
    plateforme: Any, outils: Any, client: dict[str, Any], place: str
) -> str:
    """Paiements injoignable : 503, commande EN_ATTENTE ; Paiements rétabli."""
    plateforme.paiements_injoignable()
    reponse = await plateforme.commander(client, [place])
    outils.exiger_probleme(reponse, 503, "SERVICE_INDISPONIBLE", f"commande sur {place}")
    plateforme.retablir()
    (commande,) = await plateforme.bases.commandes_de(client["sujet"])
    assert commande["statut"] == "EN_ATTENTE", commande
    return str(commande["id"])


def evenement_de(ligne: dict[str, Any]) -> Evenement:
    """Enveloppe reconstituée d'une ligne d'outbox (ce que publie le relais)."""
    return Evenement(
        id=ligne["id"],
        type=ligne["type"],
        version=ligne["version"],
        occurred_at=ligne["occurred_at"],
        correlation_id=ligne["correlation_id"],
        data=ligne["data"],
    )


async def test_une_expiration_et_un_paiement_simultanes_ne_produisent_qu_une_issue(
    plateforme_courte: Any, outils: Any
) -> None:
    plateforme = plateforme_courte
    for repetition, place in enumerate(PLACES_REPETITIONS[:REPETITIONS]):
        client = client_de_test()
        commande_id = await commande_en_attente(plateforme, outils, client, place)
        # Verrous de 2 s expirés : expire_le dépassé.
        await anyio.sleep(ATTENTE_EXPIRATION)
        await plateforme.redis.supprimer(outils.cle_tache)
        avant = len(plateforme.gateway.appels)

        async def lancer(
            numero: int, client: dict[str, Any] = client, cid: str = commande_id
        ) -> Any:
            if numero == 0:
                return await plateforme.payer(client, cid)
            return await plateforme.cycle(2)

        reponse, cycle = await outils.barriere(2, lancer)

        etape = f"répétition {repetition} ({place}) : cycle {cycle!r}"
        statut = (await plateforme.bases.commande(commande_id))["statut"]
        expirees = await plateforme.bases.evenements_de(EXPIREE, commande_id)
        confirmees = await plateforme.bases.evenements_de(CONFIRMEE, commande_id)
        postes = [
            a
            for a in plateforme.gateway.appels[avant:]
            if a.cible == CIBLE_PAIEMENTS and a.methode == "POST"
        ]
        assert not (expirees and confirmees), f"{etape} : les deux événements"
        if statut == "EXPIREE":
            assert len(expirees) == 1, f"{etape} : {expirees}"
            assert postes == [], f"{etape} : POST reçu par Paiements"
            assert reponse.status_code == 409, f"{etape} : {reponse.text}"
            # ORDER_NOT_PENDING si la tâche a expiré la commande avant sa relecture ;
            # SEAT_ALREADY_TAKEN si payerCommande l'a relue EN_ATTENTE puis a perdu le
            # reverrouillage de la place (verrou expiré, BIL-008).
            assert reponse.json()["code"] in {"ORDER_NOT_PENDING", "SEAT_ALREADY_TAKEN"}, etape
        else:
            assert statut == "CONFIRMEE", f"{etape} : statut {statut}"
            assert len(confirmees) == 1, f"{etape} : {confirmees}"
            assert reponse.status_code == 200, f"{etape} : {reponse.text}"
        assert cycle is True, etape


async def test_la_tache_n_expire_pas_une_commande_pendant_le_post_de_paiement(
    plateforme: Any, outils: Any
) -> None:
    client = client_de_test()
    commande_id = await commande_en_attente(plateforme, outils, client, "A1")
    # Échéance dépassée, verrou de la place toujours tenu : payerCommande va le reverrouiller
    # et repousser expire_le avant son POST (H3).
    await plateforme.bases.commandes.executer(
        "UPDATE commandes SET expire_le = :le WHERE id = :id",
        le=datetime.now(UTC) - timedelta(seconds=1),
        id=uuid.UUID(commande_id),
    )
    arrivee, liberation = asyncio.Event(), asyncio.Event()

    async def retenir_le_post(
        requete: httpx.Request, transport: httpx.AsyncBaseTransport
    ) -> httpx.Response:
        if requete.method == "POST":
            arrivee.set()
            await liberation.wait()
        return await transport.handle_async_request(requete)

    plateforme.gateway.intercepteurs[CIBLE_PAIEMENTS] = retenir_le_post
    paiement = asyncio.create_task(plateforme.payer(client, commande_id))
    try:
        await outils.borne("POST de paiement retenu", arrivee.wait())
        cycle = await plateforme.cycle(2)
        statut_pendant = (await plateforme.bases.commande(commande_id))["statut"]
        expirees_pendant = await plateforme.bases.evenements_de(EXPIREE, commande_id)
    finally:
        liberation.set()
    reponse = await outils.borne("payerCommande après déblocage", paiement)

    assert statut_pendant == "EN_ATTENTE", f"commande expirée pendant le POST ; cycle {cycle!r}"
    assert expirees_pendant == []
    outils.exiger_statut(reponse, 200, "payerCommande")
    assert (await plateforme.bases.commande(commande_id))["statut"] == "CONFIRMEE"
    assert await plateforme.bases.evenements_de(EXPIREE, commande_id) == []
    assert len(await plateforme.bases.evenements_de(CONFIRMEE, commande_id)) == 1
    assert [p["statut"] for p in await plateforme.bases.paiements_de(commande_id)] == ["ACCEPTE"]
    assert cycle is True, f"cycle : {cycle!r}"


async def test_une_place_liberee_par_expiration_n_est_vendue_qu_a_un_seul_client(
    plateforme: Any, urls: dict[str, str], outils: Any
) -> None:
    client_a = client_de_test()
    commande_a = await commande_en_attente(plateforme, outils, client_a, "A1")
    # Échéance de A atteinte : son verrou a disparu (comme à expiration) et expire_le est passé.
    await plateforme.redis.supprimer(plateforme.cle_redis("A1"))
    await plateforme.bases.commandes.executer(
        "UPDATE commandes SET expire_le = :le WHERE id = :id",
        le=datetime.now(UTC) - timedelta(seconds=1),
        id=uuid.UUID(commande_a),
    )
    cycle = await plateforme.cycle(1)
    assert (await plateforme.bases.commande(commande_a))["statut"] == "EXPIREE", (
        f"cycle : {cycle!r}"
    )
    (ligne_expiree,) = await plateforme.bases.evenements_de(EXPIREE, commande_a)

    moteur = create_async_engine(urls["billets"], connect_args={"timeout": 30})
    sessions_billets = async_sessionmaker(moteur, expire_on_commit=False)
    verrous = VerrousRedis(plateforme.redis.url, DELAI_REDIS)
    clients = [client_de_test() for _ in range(CLIENTS_EN_CONCURRENCE)]
    try:

        async def lancer(numero: int) -> Any:
            if numero == 0:
                # order.expired de A consommé par Billets pendant la course.
                try:
                    return await traiter_une_fois(
                        sessions_billets,
                        CONSOMMATEUR_EXPIREE,
                        functools.partial(liberer_places_de_la_commande_expiree, verrous),
                        evenement_de(ligne_expiree),
                    )
                except Exception as erreur:  # noqa: BLE001 : vérifiée après l'état
                    return erreur
            return await plateforme.commander(
                clients[numero - 1], ["A1"], instance=plateforme.instance(numero)
            )

        consommation, *reponses = await outils.barriere(CLIENTS_EN_CONCURRENCE + 1, lancer)

        statuts = Counter(r.status_code for r in reponses)
        assert statuts == {201: 1, 409: CLIENTS_EN_CONCURRENCE - 1}, (
            f"{statuts} ; consommation {consommation!r}"
        )
        perdants = [r for r in reponses if r.status_code == 409]
        assert {r.json()["code"] for r in perdants} == {"SEAT_ALREADY_TAKEN"}
        (gagnante,) = [r.json() for r in reponses if r.status_code == 201]
        assert gagnante["statut"] == "CONFIRMEE", gagnante
        # La libération de A ne supprime pas le verrou du gagnant.
        assert await plateforme.redis.valeur(plateforme.cle_redis("A1")) == gagnante["id"]
        assert consommation is True, f"consommation de order.expired : {consommation!r}"

        # Billets émis pour la commande gagnante : un seul billet pour la place.
        for ligne in await plateforme.bases.outbox(CONFIRMEE):
            await recevoir_commande_confirmee(
                sessions_billets, verrous, evenement_de(ligne), cle=CLE_QR
            )
        billets = await plateforme.bases.billets.lignes(
            "SELECT * FROM billets WHERE place_id = :place", place=plateforme.seance.places["A1"]
        )
        assert len(billets) == 1, billets
        assert str(billets[0]["commande_id"]) == gagnante["id"]
    finally:
        await verrous.fermer()
        await moteur.dispose()
