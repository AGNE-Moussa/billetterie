"""BIL-010, CA1 : consommateur `billets.order-expired` sur un vrai RabbitMQ ; un message qui
échoue trois fois finit dans `billets.order-expired.dlq` (plan docs/test-plans/BIL-010.md,
décision Q3, `.claude/rules/evenements.md`).

L'application démarre avec `rabbitmq_url` (consommateurs) ; ticketing.order.expired est publié
sur l'exchange `ticketing`.
"""

import json
import secrets
import socket
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any

import aio_pika
import anyio
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from billets.principal import creer_app
from commun.evenements import Evenement

pytestmark = pytest.mark.anyio

IMAGE_RABBITMQ = "rabbitmq:3.13.7-management-alpine"
CONSOMMATEUR = "billets.order-expired"
FILE_ERREUR = f"{CONSOMMATEUR}.dlq"
CORRELATION = "correlation-bil-010-1"
DELAI_TRAITEMENT = 30.0


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


def port_ferme() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prise:
        prise.bind(("127.0.0.1", 0))
        port: int = prise.getsockname()[1]
    return port


@pytest.fixture
def consommateur(
    database_url: str, rabbitmq_url: str, base: Any, emetteur: Any, outils: Any
) -> Callable[[str], Any]:
    """Fabrique : `async with consommateur(redis_url)` démarre une instance avec ses
    consommateurs sur le Redis donné."""

    @asynccontextmanager
    async def demarrer(redis_url: str) -> AsyncIterator[None]:
        app = creer_app(
            outils.parametres_billets(database_url, redis_url=redis_url, rabbitmq_url=rabbitmq_url),
            verificateur_jetons=emetteur.verificateur(),
        )
        async with app.router.lifespan_context(app):
            yield

    return demarrer


async def publier(rabbitmq_url: str, evenement: Evenement) -> None:
    connexion = await aio_pika.connect_robust(rabbitmq_url)
    async with connexion:
        canal = await connexion.channel()
        exchange = await canal.declare_exchange(
            "ticketing", aio_pika.ExchangeType.TOPIC, durable=True
        )
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


async def lire_file_erreur(rabbitmq_url: str) -> list[str]:
    connexion = await aio_pika.connect_robust(rabbitmq_url)
    identifiants: list[str] = []
    async with connexion:
        canal = await connexion.channel()
        file = await canal.declare_queue(FILE_ERREUR, passive=True)
        while (message := await file.get(no_ack=True, fail=False)) is not None:
            identifiants.append(str(json.loads(message.body)["id"]))
    return identifiants


async def jusqua(predicat: Callable[[], Awaitable[bool]], delai: float = DELAI_TRAITEMENT) -> bool:
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if await predicat():
            return True
        await anyio.sleep(0.5)
    return False


def order_expired(data: dict[str, Any]) -> Evenement:
    return Evenement(type="ticketing.order.expired", correlation_id=CORRELATION, data=data)


async def attendre_en_dlq(rabbitmq_url: str, message: Evenement) -> list[str]:
    en_erreur: list[str] = []

    async def en_dlq() -> bool:
        en_erreur.extend(await lire_file_erreur(rabbitmq_url))
        return str(message.id) in en_erreur

    await jusqua(en_dlq)
    return en_erreur


async def test_des_donnees_invalides_finissent_dans_la_file_dlq(
    rabbitmq_url: str, redis_url: str, seance: Any, base: Any, consommateur: Any
) -> None:
    # `data` sans place_ids.
    message = order_expired({"commande_id": str(uuid.uuid4()), "seance_id": str(seance.id)})

    async with consommateur(redis_url):
        await publier(rabbitmq_url, message)
        en_erreur = await attendre_en_dlq(rabbitmq_url, message)

    assert str(message.id) in en_erreur, f"message absent de {FILE_ERREUR} : {en_erreur}"
    assert await base.compter("messages_traites") == 0


async def test_redis_injoignable_fait_echouer_le_message_pour_un_nouvel_essai(
    rabbitmq_url: str, seance: Any, base: Any, consommateur: Any
) -> None:
    message = order_expired(
        {
            "commande_id": str(uuid.uuid4()),
            "seance_id": str(seance.id),
            "place_ids": [str(seance.places["A1"])],
        }
    )

    async with consommateur(f"redis://127.0.0.1:{port_ferme()}/0"):
        await publier(rabbitmq_url, message)
        en_erreur = await attendre_en_dlq(rabbitmq_url, message)

    assert str(message.id) in en_erreur, f"message absent de {FILE_ERREUR} : {en_erreur}"
    assert await base.compter("messages_traites") == 0
