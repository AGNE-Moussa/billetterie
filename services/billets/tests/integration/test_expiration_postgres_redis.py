"""BIL-010, CA1 et idempotence : Billets consomme `ticketing.order.expired` et libère les places
de la commande expirée (plan docs/test-plans/BIL-010.md, décision Q3, hypothèse H5).

Le traitement d'une livraison (`commun.consommateurs.traiter_une_fois` avec
`billets.consommateurs.liberer_places_de_la_commande_expiree`, comme l'abonnement du service)
est appelé directement sur la vraie base migrée et le vrai Redis du module ; la livraison par
RabbitMQ et la file d'erreur sont couvertes par test_expiration_rabbitmq.py.
"""

import functools
import socket
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from billets.consommateurs import liberer_places_de_la_commande_expiree
from billets.domaine.verrous import VerrouIndisponible
from billets.infra.verrous import VerrousRedis
from commun.consommateurs import traiter_une_fois
from commun.evenements import Evenement

pytestmark = pytest.mark.anyio

CONSOMMATEUR = "billets.order-expired"
CORRELATION = "correlation-bil-010-1"
DELAI_REDIS = 0.5


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    moteur = create_async_engine(database_url, connect_args={"timeout": 30, "command_timeout": 30})
    try:
        yield async_sessionmaker(moteur, expire_on_commit=False)
    finally:
        await moteur.dispose()


@pytest.fixture
async def verrous(redis_url: str) -> AsyncIterator[VerrousRedis]:
    magasin = VerrousRedis(redis_url, DELAI_REDIS)
    try:
        yield magasin
    finally:
        await magasin.fermer()


def port_ferme() -> int:
    """Port local libre, sans écoute : Redis injoignable (connexion refusée)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prise:
        prise.bind(("127.0.0.1", 0))
        port: int = prise.getsockname()[1]
    return port


def order_expired(
    seance_id: uuid.UUID,
    place_ids: list[uuid.UUID],
    commande_id: uuid.UUID,
    *,
    identifiant: uuid.UUID | None = None,
    remboursement_du: bool | None = None,
) -> Evenement:
    data: dict[str, Any] = {
        "commande_id": str(commande_id),
        "seance_id": str(seance_id),
        "place_ids": [str(p) for p in place_ids],
    }
    if remboursement_du is not None:
        data["remboursement_du"] = remboursement_du
    return Evenement(
        id=identifiant or uuid.uuid4(),
        type="ticketing.order.expired",
        version=1,
        correlation_id=CORRELATION,
        data=data,
    )


async def traiter(
    sessions: async_sessionmaker[AsyncSession], verrous: VerrousRedis, evenement: Evenement
) -> BaseException | None:
    """Une livraison ; rend l'exception levée (ou None) pour vérifier d'abord l'état."""
    try:
        await traiter_une_fois(
            sessions,
            CONSOMMATEUR,
            functools.partial(liberer_places_de_la_commande_expiree, verrous),
            evenement,
        )
    except Exception as erreur:  # noqa: BLE001 : classée par le test
        return erreur
    return None


async def traites(base: Any, message_id: uuid.UUID | None = None) -> list[Any]:
    requete = "SELECT * FROM messages_traites WHERE consommateur = :nom"
    if message_id is None:
        return await base.lignes(requete, nom=CONSOMMATEUR)  # type: ignore[no-any-return]
    return await base.lignes(  # type: ignore[no-any-return]
        requete + " AND message_id = :message", nom=CONSOMMATEUR, message=message_id
    )


async def verrouiller(
    plateforme: Any, seance: Any, libelle: str, commande: uuid.UUID, outils: Any
) -> None:
    reponse = await plateforme.verrouiller(seance.id, seance.places[libelle], commande)
    outils.exiger_statut(reponse, 200, f"verrou de {libelle} pour {commande}")


async def test_la_consommation_libere_les_verrous_dans_le_vrai_redis(
    plateforme: Any, seance: Any, observateur: Any, sessions: Any, verrous: Any, outils: Any
) -> None:
    commande_a = uuid.uuid4()
    for libelle in ("A1", "A2"):
        await verrouiller(plateforme, seance, libelle, commande_a, outils)
    places = [seance.places["A1"], seance.places["A2"]]

    erreur = await traiter(sessions, verrous, order_expired(seance.id, places, commande_a))

    for place in places:
        assert await observateur.valeur(outils.cle_verrou(seance.id, place)) is None, (
            f"verrou de {place} encore présent ; traitement : {erreur!r}"
        )
    disponibles = await plateforme.disponibilites(seance.id)
    assert [disponibles[str(p)] for p in places] == [True, True]
    assert erreur is None, f"traitement : {erreur!r}"


async def test_la_consommation_ne_supprime_pas_dans_redis_le_verrou_d_une_autre_commande(
    plateforme: Any, seance: Any, observateur: Any, sessions: Any, verrous: Any, outils: Any
) -> None:
    commande_a, commande_b = uuid.uuid4(), uuid.uuid4()
    await verrouiller(plateforme, seance, "A1", commande_b, outils)
    cle = outils.cle_verrou(seance.id, seance.places["A1"])
    pttl_avant = await observateur.pttl(cle)

    erreur = await traiter(
        sessions, verrous, order_expired(seance.id, [seance.places["A1"]], commande_a)
    )

    assert await observateur.valeur(cle) == str(commande_b)
    assert abs(await observateur.pttl(cle) - pttl_avant) <= 1_000
    assert (await plateforme.disponibilites(seance.id))[str(seance.places["A1"])] is False
    assert erreur is None, f"traitement : {erreur!r}"


async def test_une_place_vendue_reste_indisponible_apres_l_expiration_d_une_autre_commande(
    plateforme: Any, seance: Any, base: Any, sessions: Any, verrous: Any
) -> None:
    place = seance.places["A1"]
    billet_b = await base.inserer_billet(seance.id, place)

    erreur = await traiter(sessions, verrous, order_expired(seance.id, [place], uuid.uuid4()))

    billets = await base.lignes("SELECT id, statut FROM billets WHERE place_id = :p", p=place)
    assert [(b["id"], b["statut"]) for b in billets] == [(billet_b, "EMIS")]
    assert (await plateforme.disponibilites(seance.id))[str(place)] is False
    assert erreur is None, f"traitement : {erreur!r}"


async def test_redis_injoignable_fait_echouer_le_message_pour_un_nouvel_essai(
    seance: Any, base: Any, sessions: Any
) -> None:
    injoignable = VerrousRedis(f"redis://127.0.0.1:{port_ferme()}/0", DELAI_REDIS)
    message = order_expired(seance.id, [seance.places["A1"]], uuid.uuid4())
    try:
        erreur = await traiter(sessions, injoignable, message)
    finally:
        await injoignable.fermer()

    assert await traites(base) == [], "message inscrit malgré l'échec de Redis"
    # Décision Q3 : VerrouIndisponible remonte, d'où un nouvel essai (puis la DLQ).
    assert isinstance(erreur, VerrouIndisponible), f"exception levée : {erreur!r}"


async def test_un_message_d_expiration_rejoue_n_a_aucun_effet_de_plus(
    plateforme: Any,
    seance: Any,
    base: Any,
    observateur: Any,
    sessions: Any,
    verrous: Any,
    outils: Any,
) -> None:
    commande_a, commande_b = uuid.uuid4(), uuid.uuid4()
    await verrouiller(plateforme, seance, "A1", commande_a, outils)
    message = order_expired(seance.id, [seance.places["A1"]], commande_a)

    premiere = await traiter(sessions, verrous, message)
    await verrouiller(plateforme, seance, "A1", commande_b, outils)
    seconde = await traiter(sessions, verrous, message)

    assert len(await traites(base, message.id)) == 1
    assert await observateur.valeur(outils.cle_verrou(seance.id, seance.places["A1"])) == str(
        commande_b
    )
    assert (premiere, seconde) == (None, None)


async def test_une_meme_expiration_publiee_sous_deux_identifiants_ne_libere_que_les_verrous_de_la_commande(  # noqa: E501 : nom du plan
    plateforme: Any,
    seance: Any,
    base: Any,
    observateur: Any,
    sessions: Any,
    verrous: Any,
    outils: Any,
) -> None:
    commande_a, commande_b = uuid.uuid4(), uuid.uuid4()
    await verrouiller(plateforme, seance, "A1", commande_a, outils)
    places = [seance.places["A1"]]

    premiere = await traiter(sessions, verrous, order_expired(seance.id, places, commande_a))
    await verrouiller(plateforme, seance, "A1", commande_b, outils)
    seconde = await traiter(sessions, verrous, order_expired(seance.id, places, commande_a))

    assert len(await traites(base)) == 2
    assert await observateur.valeur(outils.cle_verrou(seance.id, seance.places["A1"])) == str(
        commande_b
    )
    assert (premiere, seconde) == (None, None)
