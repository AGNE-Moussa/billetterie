"""E5 (BIL-006, décision Q5) : le consommateur `ticketing.show.scheduled` crée les places.

Vrai RabbitMQ et vraie base : l'application démarre avec `rabbitmq_url` (consommateur
`billets.show-scheduled`, commun.consommateurs) ; les événements sont publiés sur l'exchange
`ticketing` avec la clé de routage `ticketing.show.scheduled`, dans l'enveloppe
`commun.evenements.Evenement` (données synthétiques communes du plan).
"""

import json
import logging
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import aio_pika
import anyio
import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from billets.principal import creer_app
from commun.evenements import Evenement

pytestmark = pytest.mark.anyio

IMAGE_RABBITMQ = "rabbitmq:3.13.7-management-alpine"
TYPE = "ticketing.show.scheduled"
CONSOMMATEUR = "billets.show-scheduled"
FILE_ERREUR = f"{CONSOMMATEUR}.dlq"
# Attente du traitement d'un message (trois tentatives comprises pour la DLQ).
DELAI_TRAITEMENT = 30.0
# Laisse arriver un éventuel doublon ou une remise en file après le premier effet.
ATTENTE_DOUBLON = 2.0


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
) -> AsyncIterator[httpx.AsyncClient]:
    """Instance avec consommateur RabbitMQ démarré, et son client public."""
    app = creer_app(
        outils.parametres_billets(database_url, redis_url=redis_url, rabbitmq_url=rabbitmq_url),
        verificateur_jetons=emetteur.verificateur(),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=60.0
        ) as client,
    ):
        yield client


def donnees_seance(seance_id: uuid.UUID, *, sans_categories: bool = False) -> dict[str, Any]:
    """`data` de ticketing.show.scheduled (schéma docs/evenements), séance commune du plan."""
    data: dict[str, Any] = {
        "seance_id": str(seance_id),
        "evenement_id": str(uuid.uuid4()),
        "evenement_nom": "Concert de test",
        "lieu_id": str(uuid.uuid4()),
        "lieu_nom": "Salle de test",
        "ville": "Villetest",
        "debut": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        "categories": [
            {
                "categorie_id": str(uuid.uuid4()),
                "nom": "Fosse",
                "prix": 4500,
                "rangs": [{"rang": "A", "nombre_places": 10}, {"rang": "B", "nombre_places": 12}],
            },
            {
                "categorie_id": str(uuid.uuid4()),
                "nom": "Balcon",
                "prix": 3000,
                "rangs": [{"rang": "C", "nombre_places": 5}],
            },
        ],
    }
    if sans_categories:
        del data["categories"]
    return data


def evenement(data: dict[str, Any], numero: int, identifiant: uuid.UUID | None = None) -> Evenement:
    return Evenement(
        id=identifiant or uuid.uuid4(),
        type=TYPE,
        version=1,
        correlation_id=f"correlation-bil-006-{numero}",
        data=data,
    )


async def publier(rabbitmq_url: str, *evenements: Evenement) -> None:
    """Publie sur l'exchange `ticketing` (topic, durable), comme le relais de l'outbox."""
    connexion = await aio_pika.connect_robust(rabbitmq_url)
    async with connexion:
        canal = await connexion.channel()
        exchange = await canal.declare_exchange(
            "ticketing", aio_pika.ExchangeType.TOPIC, durable=True
        )
        for un_evenement in evenements:
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(un_evenement.model_dump(mode="json")).encode(),
                    content_type="application/json",
                    message_id=str(un_evenement.id),
                    correlation_id=un_evenement.correlation_id,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=TYPE,
            )


async def lire_file_erreur(rabbitmq_url: str) -> list[str]:
    """Identifiants des messages présents dans `billets.show-scheduled.dlq` (consommés)."""
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


async def _places(base: Any, seance_id: uuid.UUID) -> int:
    return int(await base.compter("places", "seance_id = :seance", seance=seance_id))


async def _traites(base: Any) -> int:
    return int(await base.compter("messages_traites", "consommateur = :nom", nom=CONSOMMATEUR))


async def test_un_message_show_scheduled_cree_les_places_de_la_seance(
    consommateur: httpx.AsyncClient, rabbitmq_url: str, base: Any, outils: Any
) -> None:
    seance_id = uuid.uuid4()

    await publier(rabbitmq_url, evenement(donnees_seance(seance_id), 1))

    async def toutes_creees() -> bool:
        return await _places(base, seance_id) == outils.nombre_places

    await jusqua(toutes_creees)
    assert await _places(base, seance_id) == outils.nombre_places
    assert await _traites(base) == 1
    page = outils.exiger_statut(
        await consommateur.get(outils.route_places, params={"seance_id": str(seance_id)}),
        200,
        "listerPlaces après le message",
    )
    assert page["total"] == outils.nombre_places


async def test_le_meme_message_recu_deux_fois_ne_cree_les_places_qu_une_fois(
    consommateur: httpx.AsyncClient, rabbitmq_url: str, base: Any, outils: Any
) -> None:
    seance_id = uuid.uuid4()
    message = evenement(donnees_seance(seance_id), 2)

    await publier(rabbitmq_url, message, message)

    async def creees() -> bool:
        return await _places(base, seance_id) >= outils.nombre_places

    await jusqua(creees)
    await anyio.sleep(ATTENTE_DOUBLON)
    assert await _places(base, seance_id) == outils.nombre_places
    assert await _traites(base) == 1


async def test_deux_messages_simultanes_pour_la_meme_seance_ne_creent_aucun_doublon(
    consommateur: httpx.AsyncClient, rabbitmq_url: str, base: Any, outils: Any
) -> None:
    seance_id = uuid.uuid4()
    data = donnees_seance(seance_id)
    messages = (evenement(data, 3), evenement(data, 4))

    await publier(rabbitmq_url, *messages)

    async def deux_traites() -> bool:
        return await _traites(base) == 2

    await jusqua(deux_traites)
    await anyio.sleep(ATTENTE_DOUBLON)
    assert await _places(base, seance_id) == outils.nombre_places
    en_erreur = await lire_file_erreur(rabbitmq_url)
    assert not ({str(m.id) for m in messages} & set(en_erreur)), en_erreur


def donnees_grande_seance(seance_id: uuid.UUID) -> dict[str, Any]:
    """Séance de 7 000 places (7 rangs de 1 000), au-delà des 6 553 places d'un INSERT unique
    (32 767 paramètres liés au plus pour asyncpg, 5 par place) : review BIL-006, point 1."""
    data = donnees_seance(seance_id)
    data["categories"] = [
        {
            "categorie_id": str(uuid.uuid4()),
            "nom": "Fosse",
            "prix": 4500,
            "rangs": [{"rang": rang, "nombre_places": 1000} for rang in ("A", "B", "C", "D")],
        },
        {
            "categorie_id": str(uuid.uuid4()),
            "nom": "Balcon",
            "prix": 3000,
            "rangs": [{"rang": rang, "nombre_places": 1000} for rang in ("E", "F", "G")],
        },
    ]
    return data


GRANDE_SEANCE = 7000


async def test_une_seance_de_plus_de_6553_places_est_creee_entierement_et_une_seule_fois(
    consommateur: httpx.AsyncClient, rabbitmq_url: str, base: Any, outils: Any
) -> None:
    seance_id = uuid.uuid4()
    data = donnees_grande_seance(seance_id)
    premier = evenement(data, 6)

    await publier(rabbitmq_url, premier)

    async def toutes_creees() -> bool:
        return await _places(base, seance_id) == GRANDE_SEANCE

    await jusqua(toutes_creees)
    en_erreur = await lire_file_erreur(rabbitmq_url)
    assert str(premier.id) not in en_erreur, f"premier message parti en {FILE_ERREUR}"
    assert await _places(base, seance_id) == GRANDE_SEANCE
    assert await _traites(base) == 1

    # Second traitement de la même séance (autre message) : aucune place de plus.
    second = evenement(data, 7)
    await publier(rabbitmq_url, second)

    async def deux_traites() -> bool:
        return await _traites(base) == 2

    await jusqua(deux_traites)
    await anyio.sleep(ATTENTE_DOUBLON)
    assert await _traites(base) == 2
    assert await _places(base, seance_id) == GRANDE_SEANCE
    assert str(second.id) not in await lire_file_erreur(rabbitmq_url)


async def test_un_message_invalide_part_en_file_d_erreur_apres_trois_tentatives(
    consommateur: httpx.AsyncClient, rabbitmq_url: str, base: Any
) -> None:
    seance_id = uuid.uuid4()
    message = evenement(donnees_seance(seance_id, sans_categories=True), 5)
    en_erreur: list[str] = []

    await publier(rabbitmq_url, message)

    async def arrive_en_dlq() -> bool:
        en_erreur.extend(await lire_file_erreur(rabbitmq_url))
        return str(message.id) in en_erreur

    await jusqua(arrive_en_dlq)
    assert str(message.id) in en_erreur, f"message absent de {FILE_ERREUR} : {en_erreur}"
    assert await _places(base, seance_id) == 0


async def test_la_correlation_du_message_est_reprise_dans_les_journaux(
    consommateur: httpx.AsyncClient,
    rabbitmq_url: str,
    base: Any,
    outils: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    seance_id = uuid.uuid4()

    await publier(rabbitmq_url, evenement(donnees_seance(seance_id), 1))

    async def traite() -> bool:
        return await _places(base, seance_id) == outils.nombre_places

    await jusqua(traite)
    correlees = [
        record.getMessage()
        for record in caplog.records
        if getattr(record, "correlation_id", None) == "correlation-bil-006-1"
    ]
    assert correlees, "aucune ligne de journal du traitement avec correlation-bil-006-1"
