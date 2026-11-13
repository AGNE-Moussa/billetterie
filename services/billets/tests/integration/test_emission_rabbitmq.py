"""BIL-009, CA1 (H5) et E1 (Q5) : consommateur `billets.order-confirmed` sur un vrai RabbitMQ
(plan docs/test-plans/BIL-009.md).

L'application démarre avec `rabbitmq_url` (consommateurs et relais de l'outbox) ;
ticketing.order.confirmed est publié sur l'exchange `ticketing`. Une file de test, liée à
`ticketing.ticket.issued`, reçoit ce que publie le relais.
"""

import json
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
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
CONSOMMATEUR = "billets.order-confirmed"
FILE_ERREUR = f"{CONSOMMATEUR}.dlq"
CORRELATION = "correlation-bil-009-1"
DELAI_TRAITEMENT = 20.0


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
async def consommateur(
    database_url: str,
    redis_url: str,
    rabbitmq_url: str,
    base: Any,
    emetteur: Any,
    outils: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    """Instance avec consommateurs et relais de l'outbox démarrés ; clé QR dans
    l'environnement (`QR_CLE_SIGNATURE`)."""
    monkeypatch.setenv("QR_CLE_SIGNATURE", secrets.token_urlsafe(32))
    app = creer_app(
        outils.parametres_billets(database_url, redis_url=redis_url, rabbitmq_url=rabbitmq_url),
        verificateur_jetons=emetteur.verificateur(),
    )
    async with app.router.lifespan_context(app):
        yield


def order_confirmed(seance_id: uuid.UUID, place_ids: list[uuid.UUID]) -> Evenement:
    return Evenement(
        type="ticketing.order.confirmed",
        correlation_id=CORRELATION,
        data={
            "commande_id": str(uuid.uuid4()),
            "client": "client-test",
            "email": "client.test@exemple.test",
            "seance_id": str(seance_id),
            "lignes": [{"place_id": str(p), "montant": 4500} for p in place_ids],
            "montant_total": 4500 * len(place_ids),
        },
    )


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


async def test_le_consommateur_de_billets_recoit_order_confirmed_depuis_rabbitmq(
    rabbitmq_url: str, seance: Any, base: Any, consommateur: None
) -> None:
    message = order_confirmed(seance.id, [seance.places["A1"], seance.places["A2"]])
    commande_id = uuid.UUID(message.data["commande_id"])
    recus: list[dict[str, Any]] = []

    connexion = await aio_pika.connect_robust(rabbitmq_url)
    async with connexion:
        canal = await connexion.channel()
        exchange = await canal.declare_exchange(
            "ticketing", aio_pika.ExchangeType.TOPIC, durable=True
        )
        file_de_test = await canal.declare_queue(exclusive=True, auto_delete=True)
        await file_de_test.bind(exchange, routing_key="ticketing.ticket.issued")

        await publier(rabbitmq_url, message)

        async def deux_publies() -> bool:
            while (recu := await file_de_test.get(no_ack=True, fail=False)) is not None:
                recus.append(json.loads(recu.body))
            return len(recus) >= 2

        await jusqua(deux_publies)

    billets = await base.lignes("SELECT id FROM billets WHERE commande_id = :c", c=commande_id)
    assert len(billets) == 2, f"{len(billets)} billets au lieu de 2"
    assert len(recus) == 2, f"{len(recus)} ticket.issued reçus au lieu de 2"
    assert {r["data"]["billet_id"] for r in recus} == {str(b["id"]) for b in billets}


@pytest.mark.parametrize("intrus", ["place_absente", "place_d_une_autre_seance"])
async def test_une_place_inconnue_de_billets_envoie_le_message_en_dlq(
    intrus: str, rabbitmq_url: str, seance: Any, base: Any, consommateur: None
) -> None:
    if intrus == "place_absente":
        place_intruse = uuid.uuid4()
    else:
        autre = await base.semer_seance()
        place_intruse = autre.places["A1"]
    message = order_confirmed(seance.id, [seance.places["A1"], place_intruse])
    en_erreur: list[str] = []

    await publier(rabbitmq_url, message)

    async def en_dlq() -> bool:
        en_erreur.extend(await lire_file_erreur(rabbitmq_url))
        return str(message.id) in en_erreur

    await jusqua(en_dlq)
    assert str(message.id) in en_erreur, f"message absent de {FILE_ERREUR} : {en_erreur}"
    assert await base.compter("billets") == 0
    assert await base.compter("outbox") == 0
