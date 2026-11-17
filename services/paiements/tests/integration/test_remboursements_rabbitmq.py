"""BIL-011, CA1 (H5, H6) : Paiements démarré avec un vrai RabbitMQ consomme
`ticketing.show.cancelled` et `ticketing.ticket.rejected`, puis le relais de l'outbox publie
`ticketing.payment.refunded` (review docs/reviews/BIL-011.md, « À couvrir », point 9).

Application sous lifespan (`rabbitmq_url` renseignée : consommateurs `paiements.show-cancelled`,
`paiements.ticket-rejected` et relais) ; événements publiés sur l'exchange `ticketing` comme le
ferait le relais d'un autre service ; une file de test liée à `ticketing.payment.refunded`
reçoit ce que Paiements publie.
"""

import json
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import aio_pika
import anyio
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from commun.evenements import Evenement

pytestmark = pytest.mark.anyio

IMAGE_RABBITMQ = "rabbitmq:3.13.7-management-alpine"
CORRELATION = "correlation-bil-011-1"
REMBOURSE = "ticketing.payment.refunded"
DELAI = 30.0


@pytest.fixture(scope="module")
def rabbitmq_url() -> Iterator[str]:
    utilisateur, mot_de_passe = "essai", secrets.token_urlsafe(16)
    conteneur = (
        DockerContainer(IMAGE_RABBITMQ)
        .with_env("RABBITMQ_DEFAULT_USER", utilisateur)
        .with_env("RABBITMQ_DEFAULT_PASS", mot_de_passe)
        .with_exposed_ports(5672)
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
    )
    with conteneur:
        hote = conteneur.get_container_host_ip().replace("localhost", "127.0.0.1")
        yield f"amqp://{utilisateur}:{mot_de_passe}@{hote}:{conteneur.get_exposed_port(5672)}/"


@pytest.fixture
async def ecoute(rabbitmq_url: str) -> AsyncIterator[aio_pika.abc.AbstractQueue]:
    """File exclusive liée à `ticketing.payment.refunded`, créée avant toute publication."""
    connexion = await aio_pika.connect_robust(rabbitmq_url)
    async with connexion:
        canal = await connexion.channel()
        exchange = await canal.declare_exchange(
            "ticketing", aio_pika.ExchangeType.TOPIC, durable=True
        )
        file = await canal.declare_queue(exclusive=True)
        await file.bind(exchange, routing_key=REMBOURSE)
        yield file


async def publier(rabbitmq_url: str, *evenements: Evenement) -> None:
    connexion = await aio_pika.connect_robust(rabbitmq_url)
    async with connexion:
        canal = await connexion.channel()
        exchange = await canal.declare_exchange(
            "ticketing", aio_pika.ExchangeType.TOPIC, durable=True
        )
        for evenement in evenements:
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(evenement.model_dump(mode="json")).encode(),
                    content_type="application/json",
                    message_id=str(evenement.id),
                    correlation_id=evenement.correlation_id,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=evenement.type,
            )


async def recus(file: aio_pika.abc.AbstractQueue, nombre: int) -> list[dict[str, Any]]:
    """Messages de la file d'écoute dès qu'il y en a `nombre`, ou ceux reçus à l'échéance."""
    messages: list[dict[str, Any]] = []
    limite = time.monotonic() + DELAI
    while len(messages) < nombre and time.monotonic() < limite:
        message = await file.get(no_ack=True, fail=False)
        if message is None:
            await anyio.sleep(0.3)
            continue
        messages.append(json.loads(message.body))
    return messages


async def statut_final(base: Any, paiement_id: str, attendu: str) -> str:
    limite = time.monotonic() + DELAI
    while True:
        lignes = await base.lignes(
            "SELECT statut FROM paiements WHERE id = :id", id=uuid.UUID(paiement_id)
        )
        statut = str(lignes[0]["statut"])
        if statut == attendu or time.monotonic() > limite:
            return statut
        await anyio.sleep(0.3)


async def test_paiements_consomme_show_cancelled_et_publie_payment_refunded_sur_rabbitmq(
    service_paiements: Any, rabbitmq_url: str, base: Any, ecoute: Any, outils: Any
) -> None:
    s, c1 = uuid.uuid4(), uuid.uuid4()
    annulation = Evenement(
        type="ticketing.show.cancelled",
        correlation_id=CORRELATION,
        data={"seance_id": str(s), "evenement_id": str(uuid.uuid4())},
    )

    async with service_paiements(rabbitmq_url=rabbitmq_url) as service:
        reponse = await service.payer(commande_id=c1, seance_id=s, montant=9000)
        p1 = outils.exiger_statut(reponse, 201, "paiement préalable")
        await publier(rabbitmq_url, annulation, annulation)
        statut = await statut_final(base, p1["id"], "REMBOURSE")
        publies = await recus(ecoute, 1)
        await anyio.sleep(2.0)  # un doublon publié arriverait pendant cette attente
        publies += await recus(ecoute, 0)

    assert statut == "REMBOURSE"
    assert [m["data"] for m in publies] == [
        {"paiement_id": p1["id"], "commande_id": str(c1), "seance_id": str(s), "montant": 9000}
    ], publies
    assert publies[0]["type"] == REMBOURSE


async def test_paiements_consomme_ticket_rejected_et_publie_payment_refunded_sur_rabbitmq(
    service_paiements: Any, rabbitmq_url: str, base: Any, ecoute: Any, outils: Any
) -> None:
    s, c1 = uuid.uuid4(), uuid.uuid4()
    refus = Evenement(
        type="ticketing.ticket.rejected",
        correlation_id=CORRELATION,
        data={
            "commande_id": str(c1),
            "seance_id": str(s),
            "place_ids": [str(uuid.uuid4())],
            "motif": "PLACE_DEJA_VENDUE",
        },
    )

    async with service_paiements(rabbitmq_url=rabbitmq_url) as service:
        reponse = await service.payer(commande_id=c1, seance_id=s, montant=4500)
        p1 = outils.exiger_statut(reponse, 201, "paiement préalable")
        await publier(rabbitmq_url, refus)
        statut = await statut_final(base, p1["id"], "REMBOURSE")
        publies = await recus(ecoute, 1)

    assert statut == "REMBOURSE"
    assert [m["data"]["paiement_id"] for m in publies] == [p1["id"]], publies
