"""E6 (BIL-004, décision Q16) : le relais de l'outbox, démarré par le lifespan de catalogue,
publie `ticketing.show.scheduled` sur l'exchange `ticketing` d'un vrai RabbitMQ.

Une file de test exclusive est liée à `ticketing` sur la clé `ticketing.show.scheduled` avant
la création de la séance ; le message reçu est comparé à la ligne de l'outbox.
"""

import json
import secrets
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aio_pika
import anyio
import httpx
import pytest
from fastapi import FastAPI
from jsonschema import Draft202012Validator
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from catalogue.config import Parametres
from catalogue.principal import creer_app
from commun.faux_jetons import EmetteurDeTest

pytestmark = pytest.mark.anyio

IMAGE_RABBITMQ = "rabbitmq:3.13.7-management-alpine"
TYPE = "ticketing.show.scheduled"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[4] / "docs" / "evenements" / f"{TYPE}.json").read_text(
        encoding="utf-8"
    )
)
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
    """File exclusive liée à l'exchange ticketing sur la clé du type publié."""
    connexion = await aio_pika.connect_robust(rabbitmq_url)
    async with connexion:
        canal = await connexion.channel()
        # Mêmes paramètres que commun.outbox.EXCHANGE_TICKETING (topic, durable).
        exchange = await canal.declare_exchange(
            "ticketing", aio_pika.ExchangeType.TOPIC, durable=True
        )
        file = await canal.declare_queue(exclusive=True, auto_delete=True)
        await file.bind(exchange, routing_key=TYPE)
        yield file


@pytest.fixture
async def client_avec_relais(
    database_url: str, rabbitmq_url: str, base: Any
) -> AsyncIterator[httpx.AsyncClient]:
    emetteur = EmetteurDeTest()
    app: FastAPI = creer_app(
        Parametres(
            database_url=database_url,
            instance="catalogue-test",
            consul_actif=False,
            rabbitmq_url=rabbitmq_url,
        ),
        verificateur_jetons=emetteur.verificateur(),
    )
    entetes = emetteur.entetes(roles=["admin"], scopes=["events:read", "events:write"])
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=entetes, timeout=60.0
        ) as client:
            yield client


async def _recevoir(file: aio_pika.abc.AbstractQueue) -> aio_pika.abc.AbstractIncomingMessage:
    limite = time.monotonic() + DELAI_RECEPTION
    while time.monotonic() < limite:
        message = await file.get(no_ack=True, fail=False)
        if message is not None:
            return message
        await anyio.sleep(0.5)
    raise AssertionError(
        f"aucun message {TYPE} reçu sur l'exchange ticketing en {DELAI_RECEPTION:.0f} s"
    )


async def _ligne_marquee(base: Any) -> Any:
    """Ligne de l'outbox une fois marquée envoyée (le marquage suit la confirmation)."""
    limite = time.monotonic() + DELAI_RECEPTION
    lignes = await base.outbox()
    while time.monotonic() < limite:
        lignes = await base.outbox()
        if len(lignes) == 1 and lignes[0]["envoye_le"] is not None:
            return lignes[0]
        await anyio.sleep(0.5)
    raise AssertionError(f"ligne de l'outbox jamais marquée envoyée : {lignes}")


async def test_le_relais_publie_l_evenement_sur_l_exchange_ticketing(
    client_avec_relais: httpx.AsyncClient,
    file_de_test: aio_pika.abc.AbstractQueue,
    base: Any,
) -> None:
    client = client_avec_relais
    evenement = await client.post(
        "/api/v1/events", json={"nom": "Concert de test", "description": "Description synthétique"}
    )
    assert evenement.status_code == 201, evenement.text
    lieu = await client.post(
        "/api/v1/venues",
        json={"nom": "Salle de test", "adresse": "1 rue de l'Exemple", "ville": "Villetest"},
    )
    assert lieu.status_code == 201, lieu.text
    seance = await client.post(
        f"/api/v1/events/{evenement.json()['id']}/shows",
        json={
            "lieu_id": lieu.json()["id"],
            "debut": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "categories": [
                {"nom": "Fosse", "prix": 4500, "rangs": [{"rang": "A", "nombre_places": 10}]}
            ],
        },
        headers={"X-Correlation-Id": "correlation-bil-004-2"},
    )
    assert seance.status_code == 201, seance.text

    message = await _recevoir(file_de_test)

    ligne = await _ligne_marquee(base)
    assert message.message_id == str(ligne["id"])
    assert message.correlation_id == "correlation-bil-004-2"
    corps = json.loads(message.body)
    validateur = Draft202012Validator(SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER)
    assert [e.message for e in validateur.iter_errors(corps)] == []
    assert corps["data"]["seance_id"] == seance.json()["id"]
