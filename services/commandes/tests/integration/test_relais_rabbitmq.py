"""CA3 (BIL-008, décision Q23) : le relais de l'outbox, démarré par le lifespan de Commandes
quand `RABBITMQ_URL` est donnée, publie `ticketing.order.confirmed` sur l'exchange `ticketing`
d'un vrai RabbitMQ.
"""

import secrets
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager
from typing import Any

import aio_pika
import anyio
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

pytestmark = pytest.mark.anyio

IMAGE_RABBITMQ = "rabbitmq:3.13.7-management-alpine"
TYPE = "ticketing.order.confirmed"
DELAI_RECEPTION = 30.0


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
async def file_de_test(rabbitmq_url: str) -> AsyncIterator[aio_pika.abc.AbstractQueue]:
    """File exclusive liée à l'exchange ticketing sur la clé ticketing.order.confirmed."""
    connexion = await aio_pika.connect_robust(rabbitmq_url)
    async with connexion:
        canal = await connexion.channel()
        exchange = await canal.declare_exchange(
            "ticketing", aio_pika.ExchangeType.TOPIC, durable=True
        )
        file = await canal.declare_queue(exclusive=True, auto_delete=True)
        await file.bind(exchange, routing_key=TYPE)
        yield file


async def _recevoir(file: aio_pika.abc.AbstractQueue) -> aio_pika.abc.AbstractIncomingMessage:
    limite = time.monotonic() + DELAI_RECEPTION
    while time.monotonic() < limite:
        message = await file.get(no_ack=True, fail=False)
        if message is not None:
            return message
        await anyio.sleep(0.5)
    raise AssertionError(f"aucun message {TYPE} reçu en {DELAI_RECEPTION:.0f} s")


async def test_le_relais_publie_order_confirmed_sur_l_exchange_ticketing(
    plateforme_commandes: Callable[..., AbstractAsyncContextManager[Any]],
    rabbitmq_url: str,
    file_de_test: aio_pika.abc.AbstractQueue,
    outils: Any,
) -> None:
    async with plateforme_commandes(commandes={"rabbitmq_url": rabbitmq_url}) as plateforme:
        reponse = await plateforme.commander("A", ["A1"])
        corps = outils.exiger_statut(reponse, 201, "A commande A1")
        message = await _recevoir(file_de_test)

    (ligne,) = await plateforme.bases.evenements_de(TYPE, corps["id"])
    assert message.message_id == str(ligne["id"])
