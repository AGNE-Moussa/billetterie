"""BIL-010, CA1 de bout en bout : une commande non payée expire par la tâche de Commandes, son
`ticketing.order.expired` est relayé sur un vrai RabbitMQ et consommé par Billets, et sa place
redevient achetable (plan docs/test-plans/BIL-010.md).

Vrais Commandes (relais de l'outbox et tâche d'expiration démarrés par le lifespan, période
1 s) et Billets (consommateurs démarrés par le lifespan), vraie base, vrai Redis, vrai RabbitMQ
(Testcontainers) ; durées de verrou de Billets à 2 s.
"""

import secrets
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager
from typing import Any

import anyio
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

pytestmark = pytest.mark.anyio

IMAGE_RABBITMQ = "rabbitmq:3.13.7-management-alpine"
EXPIREE = "ticketing.order.expired"
CONSOMMATEUR = "billets.order-expired"
DUREES_COURTES = {"duree_verrou_reservation": 2, "duree_verrou_confirmation": 2}
PERIODE = 1.0
DELAI_EXPIRATION = 15.0
DELAI_CONSOMMATION = 20.0


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


async def jusqua(predicat: Callable[[], Awaitable[bool]], delai: float) -> bool:
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        if await predicat():
            return True
        await anyio.sleep(0.5)
    return False


async def test_une_commande_non_payee_expire_et_sa_place_redevient_achetable(
    plateforme_commandes: Callable[..., AbstractAsyncContextManager[Any]],
    rabbitmq_url: str,
    outils: Any,
) -> None:
    async with plateforme_commandes(
        billets={**DUREES_COURTES, "rabbitmq_url": rabbitmq_url},
        commandes={"rabbitmq_url": rabbitmq_url, "expiration_periode": PERIODE},
    ) as plateforme:
        # A laissée EN_ATTENTE : Paiements répond 503 (injoignable), puis rétabli.
        plateforme.paiements_injoignable()
        reponse_a = await plateforme.commander("A", ["A1"])
        outils.exiger_probleme(reponse_a, 503, "SERVICE_INDISPONIBLE", "A commande A1")
        plateforme.retablir()
        (commande_a,) = await plateforme.bases.commandes_de("client-a")
        commande_id = str(commande_a["id"])

        async def expiree() -> bool:
            commande = await plateforme.bases.commande(commande_id)
            return bool(commande["statut"] == "EXPIREE")

        async def consommee() -> bool:
            traites = await plateforme.bases.billets.compter(
                "SELECT 1 FROM messages_traites WHERE consommateur = :nom", nom=CONSOMMATEUR
            )
            return traites >= 1

        a_expire = await jusqua(expiree, DELAI_EXPIRATION)
        consomme = a_expire and await jusqua(consommee, DELAI_CONSOMMATION)

        assert a_expire, f"A toujours {commande_a['statut']} après {DELAI_EXPIRATION:.0f} s"
        assert len(await plateforme.bases.evenements_de(EXPIREE, commande_id)) == 1
        assert consomme, f"{EXPIREE} non consommé par Billets ({CONSOMMATEUR})"
        places = outils.exiger_statut(
            await plateforme.billets.get(
                outils.route_places,
                params={"seance_id": str(plateforme.seance.id), "size": 100},
            ),
            200,
            "listerPlaces",
        )
        disponibles = {p["id"]: p["disponible"] for p in places["elements"]}
        assert disponibles[str(plateforme.seance.places["A1"])] is True

        reponse_b = await plateforme.commander("B", ["A1"])
        outils.exiger_statut(reponse_b, 201, "B commande A1 après l'expiration de A")
