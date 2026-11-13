"""BIL-009, CA1, CA2, CA3 : chaîne complète « commande confirmée → billets → e-mails » (plan
docs/test-plans/BIL-009.md).

Conteneurs : PostgreSQL 16 pour Billets et pour Notifications (migrés par leurs propres
alembic.ini), Redis 7, RabbitMQ, Mailpit (`axllent/mailpit:v1.27.10`, même image que
compose.yaml). Les deux services démarrent sous lifespan avec leurs consommateurs ; le relais de
l'outbox de Billets publie `ticketing.ticket.issued`. ticketing.order.confirmed est publié sur
l'exchange `ticketing`, comme le ferait le relais de Commandes.

Données synthétiques : séance `S` (A1 à A4), commande `C1` (A1, A2, `client.test@exemple.test`) ;
clé QR tirée au hasard (`QR_CLE_SIGNATURE`).
"""

import json
import os
import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import aio_pika
import anyio
import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from billets.config import Parametres as ParametresBillets
from billets.domaine.qr import verifier_qr
from billets.principal import creer_app as creer_billets
from commun.evenements import Evenement
from commun.faux_jetons import EmetteurDeTest
from notifications.config import Parametres as ParametresNotifications
from notifications.principal import creer_app as creer_notifications

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[2]
IMAGE_POSTGRES = "postgres:16.10-alpine"
IMAGE_REDIS = "redis:7.4.6-alpine"
IMAGE_RABBITMQ = "rabbitmq:3.13.7-management-alpine"
IMAGE_MAILPIT = "axllent/mailpit:v1.27.10"
EMAIL_C1 = "client.test@exemple.test"
CORRELATION = "correlation-bil-009-1"
DELAI_CHAINE = 30.0
ATTENTE_DOUBLON = 3.0
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}
# Format du QR (rules/billets-qr.md, H3) : `<billet_id>.<signature base64url>`.
MOTIF_QR = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.[A-Za-z0-9_-]+"
)


def _hote(conteneur: DockerContainer) -> str:
    # Sous Windows, « localhost » passe d'abord par IPv6 et Docker Desktop coupe la connexion.
    return conteneur.get_container_host_ip().replace("localhost", "127.0.0.1")


def _migrer(service: str, database_url: str) -> None:
    precedente = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        command.upgrade(Config(str(RACINE / "services" / service / "alembic.ini")), "head")
    finally:
        if precedente is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = precedente


def _base(service: str) -> Iterator[str]:
    mot_de_passe = secrets.token_urlsafe(16)
    with PostgresContainer(
        IMAGE_POSTGRES, username=service, password=mot_de_passe, dbname=service
    ) as pg:
        url = (
            f"postgresql+asyncpg://{service}:{mot_de_passe}@{_hote(pg)}:"
            f"{pg.get_exposed_port(5432)}/{service}"
        )
        _migrer(service, url)
        yield url


@pytest.fixture(scope="module")
def url_billets() -> Iterator[str]:
    yield from _base("billets")


@pytest.fixture(scope="module")
def url_notifications() -> Iterator[str]:
    yield from _base("notifications")


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    conteneur = (
        DockerContainer(IMAGE_REDIS)
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with conteneur:
        yield f"redis://{_hote(conteneur)}:{conteneur.get_exposed_port(6379)}/0"


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
        yield (
            f"amqp://{utilisateur}:{mot_de_passe}@{_hote(conteneur)}:"
            f"{conteneur.get_exposed_port(5672)}/"
        )


@pytest.fixture(scope="module")
def mailpit() -> Iterator[DockerContainer]:
    conteneur = DockerContainer(IMAGE_MAILPIT).with_exposed_ports(1025, 8025)
    with conteneur:
        api = f"http://{_hote(conteneur)}:{conteneur.get_exposed_port(8025)}"
        limite = time.monotonic() + 60
        while True:
            try:
                if httpx.get(f"{api}/api/v1/messages", timeout=2.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > limite:
                raise TimeoutError("Mailpit n'a pas démarré à temps")
            time.sleep(0.5)
        yield conteneur


async def _sql(url: str, requete: str, **parametres: Any) -> list[Any]:
    moteur = create_async_engine(url, connect_args=CONNEXION_BORNEE)
    try:
        async with moteur.begin() as connexion:
            resultat = await connexion.execute(sa.text(requete), parametres)
            return list(resultat.mappings()) if resultat.returns_rows else []
    finally:
        await moteur.dispose()


class Mailpit:
    def __init__(self, conteneur: DockerContainer) -> None:
        self.api = f"http://{_hote(conteneur)}:{conteneur.get_exposed_port(8025)}"

    async def messages(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            reponse = await client.get(f"{self.api}/api/v1/messages")
            reponse.raise_for_status()
            return list(reponse.json().get("messages") or [])

    async def texte(self, identifiant: str) -> str:
        async with httpx.AsyncClient(timeout=10.0) as client:
            reponse = await client.get(f"{self.api}/api/v1/message/{identifiant}")
            reponse.raise_for_status()
            return str(reponse.json().get("Text") or "")

    async def vider(self) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            (await client.delete(f"{self.api}/api/v1/messages")).raise_for_status()

    async def attendre(self, nombre: int, delai: float = DELAI_CHAINE) -> list[dict[str, Any]]:
        limite = time.monotonic() + delai
        while True:
            recus = await self.messages()
            if len(recus) >= nombre or time.monotonic() > limite:
                return recus
            await anyio.sleep(0.5)


class Chaine:
    """Les deux services démarrés, la séance `S` semée dans Billets, la clé QR."""

    def __init__(
        self,
        url_billets: str,
        boite: Mailpit,
        rabbitmq_url: str,
        cle: str,
        places: dict[str, uuid.UUID],
        seance_id: uuid.UUID,
    ) -> None:
        self.url_billets = url_billets
        self.boite = boite
        self.rabbitmq_url = rabbitmq_url
        self.cle = cle
        self.places = places
        self.seance_id = seance_id

    def c1(self) -> Evenement:
        return Evenement(
            type="ticketing.order.confirmed",
            correlation_id=CORRELATION,
            data={
                "commande_id": str(uuid.uuid4()),
                "client": "client-test",
                "email": EMAIL_C1,
                "seance_id": str(self.seance_id),
                "lignes": [
                    {"place_id": str(self.places[x]), "montant": 4500} for x in ("A1", "A2")
                ],
                "montant_total": 9000,
            },
        )

    async def publier(self, *evenements: Evenement) -> None:
        connexion = await aio_pika.connect_robust(self.rabbitmq_url)
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

    async def billets(self, evenement: Evenement) -> list[Any]:
        return await _sql(
            self.url_billets,
            "SELECT id, qr_code FROM billets WHERE commande_id = :c",
            c=uuid.UUID(evenement.data["commande_id"]),
        )


@pytest.fixture
async def chaine(
    url_billets: str,
    url_notifications: str,
    redis_url: str,
    rabbitmq_url: str,
    mailpit: DockerContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Chaine]:
    cle = secrets.token_urlsafe(32)
    monkeypatch.setenv("QR_CLE_SIGNATURE", cle)
    await _sql(url_billets, "TRUNCATE billets, places, outbox, messages_traites CASCADE")
    await _sql(
        url_notifications,
        "TRUNCATE envois, destinataires_commande, outbox, messages_traites CASCADE",
    )
    boite = Mailpit(mailpit)
    await boite.vider()
    seance_id, categorie_id = uuid.uuid4(), uuid.uuid4()
    places = {f"A{n}": uuid.uuid4() for n in range(1, 5)}
    for libelle, place_id in places.items():
        await _sql(
            url_billets,
            "INSERT INTO places (id, seance_id, rang, numero, categorie_id)"
            " VALUES (:id, :seance, 'A', :numero, :categorie)",
            id=place_id,
            seance=seance_id,
            numero=int(libelle[1:]),
            categorie=categorie_id,
        )
    emetteur = EmetteurDeTest()
    billets = creer_billets(
        ParametresBillets(
            database_url=url_billets,
            redis_url=redis_url,
            rabbitmq_url=rabbitmq_url,
            consul_actif=False,
            instance="billets-test",
        ),
        verificateur_jetons=emetteur.verificateur(),
    )
    notifications = creer_notifications(
        ParametresNotifications(
            database_url=url_notifications,
            rabbitmq_url=rabbitmq_url,
            consul_actif=False,
            instance="notifications-test",
            smtp_hote=_hote(mailpit),
            smtp_port=int(mailpit.get_exposed_port(1025)),
        ),
        verificateur_jetons=emetteur.verificateur(),
    )
    async with (
        billets.router.lifespan_context(billets),
        notifications.router.lifespan_context(notifications),
    ):
        yield Chaine(url_billets, boite, rabbitmq_url, cle, places, seance_id)


async def test_un_order_confirmed_publie_produit_un_e_mail_par_billet_dans_mailpit(
    chaine: Chaine,
) -> None:
    commande = chaine.c1()

    await chaine.publier(commande)
    recus = await chaine.boite.attendre(2)

    assert len(recus) == 2, f"{len(recus)} e-mails dans Mailpit au lieu de 2"
    assert all([d["Address"] for d in r["To"]] == [EMAIL_C1] for r in recus)
    billets = await chaine.billets(commande)
    assert len(billets) == 2
    textes = [await chaine.boite.texte(r["ID"]) for r in recus]
    for billet in billets:
        porteurs = [t for t in textes if billet["qr_code"] in t]
        assert len(porteurs) == 1, f"QR du billet {billet['id']} dans {len(porteurs)} e-mails"


async def test_le_qr_recu_par_e_mail_est_verifiable_par_billets(chaine: Chaine) -> None:
    commande = chaine.c1()

    await chaine.publier(commande)
    recus = await chaine.boite.attendre(2)

    assert len(recus) == 2, f"{len(recus)} e-mails dans Mailpit au lieu de 2"
    identifiants = {b["id"] for b in await chaine.billets(commande)}
    verifies = set()
    for recu in recus:
        contenus = MOTIF_QR.findall(await chaine.boite.texte(recu["ID"]))
        assert len(contenus) == 1, f"contenu du QR introuvable dans le corps : {contenus}"
        verifies.add(verifier_qr(contenus[0], cle=chaine.cle))
    assert verifies == identifiants


async def test_un_order_confirmed_livre_deux_fois_ne_produit_qu_un_e_mail_par_billet(
    chaine: Chaine,
) -> None:
    commande = chaine.c1()

    await chaine.publier(commande, commande)
    await chaine.boite.attendre(2)
    await anyio.sleep(ATTENTE_DOUBLON)

    recus = await chaine.boite.messages()
    assert len(recus) == 2, f"{len(recus)} e-mails au lieu de 2"
    assert len(await chaine.billets(commande)) == 2
