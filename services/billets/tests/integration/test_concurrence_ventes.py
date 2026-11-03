"""BIL-007 : jamais deux ventes de la même place (plan docs/test-plans/BIL-007.md).

CA1 : 100 verrouillages simultanés de la même place, répartis sur les deux instances du
conftest (`billets-1` et `billets-2`, même base et même Redis), dix exécutions de suite (Q2) ;
une « vente » est un verrou obtenu (Q1). Les appels partent après une barrière et doivent se
chevaucher réellement (Q3). Tout 5xx fait échouer le test (Q10).

CA2 : sans Redis, N transactions simultanées insèrent un billet pour la même place sur la vraie
base du module ; seule la contrainte `uq_billets_place` empêche la double vente. N = 50 (Q5 :
`max_connections` de PostgreSQL inchangé), dix exécutions de suite (Q6).

Chaque exécution repart de fixtures neuves (base et Redis vidés, nouvelle séance, deux nouvelles
instances). Marqueur `concurrence` : joué par `make test-concurrence` (Q8).
"""

import asyncio
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

TENTATIVES = 100
INSERTIONS_SIMULTANEES = 50
EXECUTIONS = pytest.mark.parametrize(
    "execution", range(1, 11), ids=[f"execution-{n:02d}" for n in range(1, 11)]
)
DUREE_RESERVATION_MS = 600_000
CONNEXION_BORNEE = {"timeout": 30, "command_timeout": 30}
INSERER_BILLET = sa.text(
    "INSERT INTO billets (id, commande_id, client, seance_id, place_id, statut, qr_code, emis_le)"
    " VALUES (:id, :commande_id, :client, :seance_id, :place_id, :statut, :qr_code, :emis_le)"
)


# --- CA1 : verrouillages simultanés par l'API -------------------------------------------------


@dataclass(frozen=True)
class Tentative:
    commande_id: uuid.UUID
    reponse: httpx.Response
    depart: float
    arrivee: float


async def _barriere[T](nombre: int, appel: Callable[[int], Awaitable[T]]) -> list[T]:
    """Crée `nombre` tâches, attend qu'elles soient toutes prêtes, puis les libère ensemble."""
    prets = 0
    tous_prets = asyncio.Event()
    depart = asyncio.Event()

    async def tache(numero: int) -> T:
        nonlocal prets
        prets += 1
        if prets == nombre:
            tous_prets.set()
        await depart.wait()
        return await appel(numero)

    taches = [asyncio.create_task(tache(numero)) for numero in range(nombre)]
    await tous_prets.wait()
    depart.set()
    return list(await asyncio.gather(*taches))


async def _verrouillages_simultanes(
    plateforme: Any, seance_id: uuid.UUID, place: uuid.UUID, commandes: list[uuid.UUID]
) -> list[Tentative]:
    """Un PUT .../lock par commande, réparti sur les deux instances (Q4), lancés ensemble."""

    async def verrouiller(numero: int) -> Tentative:
        depart = time.monotonic()
        reponse = await plateforme.verrouiller(
            seance_id, place, commandes[numero], client=plateforme.instance(numero)
        )
        return Tentative(commandes[numero], reponse, depart, time.monotonic())

    return await _barriere(len(commandes), verrouiller)


async def _cent_verrouillages(
    plateforme: Any, seance: Any, libelle: str, outils: Any
) -> list[Tentative]:
    commandes = [uuid.uuid4() for _ in range(TENTATIVES)]
    tentatives: list[Tentative] = await outils.borne(
        f"{TENTATIVES} PUT simultanés sur {libelle}",
        _verrouillages_simultanes(plateforme, seance.id, seance.places[libelle], commandes),
    )
    erreurs_serveur = [
        (t.reponse.status_code, t.reponse.text[:200])
        for t in tentatives
        if t.reponse.status_code >= 500
    ]
    assert erreurs_serveur == [], f"5xx sous la charge (Q10) : {erreurs_serveur}"
    return tentatives


def _statuts(tentatives: list[Tentative]) -> Counter[int]:
    return Counter(t.reponse.status_code for t in tentatives)


@EXECUTIONS
async def test_cent_verrouillages_simultanes_de_la_meme_place_n_ont_qu_un_gagnant(
    execution: int,
    plateforme: Any,
    seance: Any,
    base: Any,
    observateur: Any,
    outils: Any,
) -> None:
    place = seance.places["A1"]

    tentatives = await _cent_verrouillages(plateforme, seance, "A1", outils)

    statuts = _statuts(tentatives)
    assert statuts == {200: 1, 409: TENTATIVES - 1}, f"exécution {execution} : {statuts}"
    for tentative in tentatives:
        if tentative.reponse.status_code == 409:
            outils.exiger_probleme(
                tentative.reponse, 409, "SEAT_ALREADY_TAKEN", f"exécution {execution}, refus"
            )
    (gagnant,) = [t.commande_id for t in tentatives if t.reponse.status_code == 200]

    cle = outils.cle_verrou(seance.id, place)
    assert await observateur.cles() == [cle], f"exécution {execution}"
    assert await observateur.valeur(cle) == str(gagnant), f"exécution {execution}"
    pttl = await observateur.pttl(cle)
    assert 0 < pttl <= DUREE_RESERVATION_MS, f"exécution {execution} : PTTL {pttl}"
    assert await base.compter("billets") == 0, f"exécution {execution}"


async def test_les_cent_verrouillages_partent_reellement_en_meme_temps(
    plateforme: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    tentatives = await _cent_verrouillages(plateforme, seance, "B1", outils)

    dernier_depart = max(t.depart for t in tentatives)
    premiere_reponse = min(t.arrivee for t in tentatives)
    assert dernier_depart < premiere_reponse, (
        "les appels ne se chevauchent pas : dernier départ "
        f"{dernier_depart - premiere_reponse:+.4f} s après la première réponse"
    )
    assert _statuts(tentatives) == {200: 1, 409: TENTATIVES - 1}, _statuts(tentatives)


async def test_apres_cent_verrouillages_simultanes_seule_la_place_disputee_est_indisponible(
    plateforme: Any, seance: Any, observateur: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    tentatives = await _cent_verrouillages(plateforme, seance, "A1", outils)
    assert _statuts(tentatives) == {200: 1, 409: TENTATIVES - 1}, _statuts(tentatives)
    cle = outils.cle_verrou(seance.id, place)
    valeur_avant = await observateur.valeur(cle)

    disponibles = await plateforme.disponibilites(seance.id)

    assert len(disponibles) == outils.nombre_places, disponibles
    assert disponibles[str(place)] is False
    autres = {pid: dispo for pid, dispo in disponibles.items() if pid != str(place)}
    assert all(autres.values()), [pid for pid, dispo in autres.items() if not dispo]

    retardataire = await plateforme.verrouiller(seance.id, place, uuid.uuid4())
    outils.exiger_probleme(retardataire, 409, "SEAT_ALREADY_TAKEN", "101e commande sur A1")
    assert await observateur.valeur(cle) == valeur_avant
    assert await observateur.cles() == [cle]


# --- CA2 : la base seule refuse la double vente -----------------------------------------------


@dataclass(frozen=True)
class Insertion:
    billet_id: uuid.UUID
    seance_id: uuid.UUID
    erreur: BaseException | None


def _billet(seance_id: uuid.UUID, place_id: uuid.UUID, commande_id: uuid.UUID) -> dict[str, Any]:
    billet_id = uuid.uuid4()
    return {
        "id": billet_id,
        "commande_id": commande_id,
        "client": "client.test@exemple.test",
        "seance_id": seance_id,
        "place_id": place_id,
        "statut": "EMIS",
        "qr_code": f"qr-de-test-{billet_id}",
        "emis_le": datetime.now(UTC),
    }


async def _insertions_simultanees(
    database_url: str, billets: list[dict[str, Any]], outils: Any
) -> list[Insertion]:
    """Une connexion par billet, ouverte d'avance ; barrière ; INSERT puis COMMIT de chacune.

    Toute exception est rendue (pas seulement IntegrityError) : le test exige ensuite qu'il
    n'y ait ni interblocage ni délai dépassé.
    """
    moteur = create_async_engine(database_url, poolclass=NullPool, connect_args=CONNEXION_BORNEE)
    try:
        async with AsyncExitStack() as pile:
            connexions: list[AsyncConnection] = [
                await pile.enter_async_context(moteur.connect()) for _ in billets
            ]

            async def inserer(numero: int) -> Insertion:
                billet = billets[numero]
                try:
                    async with connexions[numero].begin():
                        await connexions[numero].execute(INSERER_BILLET, billet)
                except Exception as erreur:  # noqa: BLE001 : classée par le test
                    return Insertion(billet["id"], billet["seance_id"], erreur)
                return Insertion(billet["id"], billet["seance_id"], None)

            resultats: list[Insertion] = await outils.borne(
                f"{len(billets)} insertions simultanées", _barriere(len(billets), inserer)
            )
            return resultats
    finally:
        await moteur.dispose()


def _contrainte(erreur: BaseException | None) -> str:
    """Nom de la contrainte violée, ou description de l'erreur si ce n'en est pas une."""
    if isinstance(erreur, IntegrityError):
        for nom in ("uq_billets_place", "fk_billets_place"):
            if nom in str(erreur):
                return nom
    return f"{type(erreur).__name__}: {str(erreur)[:200]}"


@EXECUTIONS
async def test_des_insertions_simultanees_de_billets_pour_la_meme_place_n_en_valident_qu_une(
    execution: int, database_url: str, base: Any, seance: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    billets = [_billet(seance.id, place, uuid.uuid4()) for _ in range(INSERTIONS_SIMULTANEES)]

    insertions = await _insertions_simultanees(database_url, billets, outils)

    validees = [i for i in insertions if i.erreur is None]
    assert len(validees) == 1, f"exécution {execution} : {len(validees)} insertions validées"
    refus = Counter(_contrainte(i.erreur) for i in insertions if i.erreur is not None)
    assert refus == {"uq_billets_place": INSERTIONS_SIMULTANEES - 1}, (
        f"exécution {execution} : {refus}"
    )
    lignes = await base.lignes("SELECT id FROM billets WHERE place_id = :place", place=place)
    assert [ligne["id"] for ligne in lignes] == [validees[0].billet_id], f"exécution {execution}"


async def test_deux_commandes_dont_le_verrou_redis_a_disparu_n_obtiennent_qu_un_billet(
    database_url: str,
    plateforme: Any,
    seance: Any,
    base: Any,
    observateur: Any,
    outils: Any,
) -> None:
    place = seance.places["A1"]
    cle = outils.cle_verrou(seance.id, place)
    commande_a, commande_b = uuid.uuid4(), uuid.uuid4()

    premier = await plateforme.verrouiller(
        seance.id, place, commande_a, client=plateforme.instance_1
    )
    outils.exiger_statut(premier, 200, "verrou de commande_a")
    await observateur.supprimer(cle)  # perte du verrou : Redis redémarré sans persistance
    second = await plateforme.verrouiller(
        seance.id, place, commande_b, client=plateforme.instance_2
    )
    outils.exiger_statut(second, 200, "verrou de commande_b après la perte de la clé")

    insertions = await _insertions_simultanees(
        database_url,
        [_billet(seance.id, place, commande_a), _billet(seance.id, place, commande_b)],
        outils,
    )

    validees = [i for i in insertions if i.erreur is None]
    assert len(validees) == 1, insertions
    refus = [_contrainte(i.erreur) for i in insertions if i.erreur is not None]
    assert refus == ["uq_billets_place"], refus
    assert await base.compter("billets", "place_id = :place", place=place) == 1

    await observateur.supprimer(cle)  # sans clé Redis, seul le billet en base peut refuser
    assert await observateur.valeur(cle) is None
    retardataire = await plateforme.verrouiller(seance.id, place, uuid.uuid4())
    outils.exiger_probleme(retardataire, 409, "SEAT_ALREADY_TAKEN", "verrou d'une place vendue")


async def test_des_insertions_simultanees_sous_une_autre_seance_que_celle_de_la_place_ne_creent_aucune_double_vente(  # noqa: E501 : nom du plan
    database_url: str, base: Any, seance: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    autre_seance = uuid.uuid4()
    moitie = INSERTIONS_SIMULTANEES // 2
    billets = [_billet(seance.id, place, uuid.uuid4()) for _ in range(moitie)] + [
        _billet(autre_seance, place, uuid.uuid4()) for _ in range(INSERTIONS_SIMULTANEES - moitie)
    ]

    insertions = await _insertions_simultanees(database_url, billets, outils)

    validees = [i for i in insertions if i.erreur is None]
    assert len(validees) == 1, f"{len(validees)} insertions validées"
    assert validees[0].seance_id == seance.id
    refus_autre = Counter(_contrainte(i.erreur) for i in insertions if i.seance_id == autre_seance)
    assert refus_autre == {"fk_billets_place": INSERTIONS_SIMULTANEES - moitie}, refus_autre
    refus_meme = Counter(
        _contrainte(i.erreur)
        for i in insertions
        if i.seance_id == seance.id and i.erreur is not None
    )
    assert refus_meme == {"uq_billets_place": moitie - 1}, refus_meme
    lignes = await base.lignes(
        "SELECT id, seance_id FROM billets WHERE place_id = :place", place=place
    )
    assert [(ligne["id"], ligne["seance_id"]) for ligne in lignes] == [
        (validees[0].billet_id, seance.id)
    ]


async def test_un_billet_annule_bloque_toujours_les_insertions_simultanees_sur_sa_place(
    database_url: str, base: Any, seance: Any, outils: Any
) -> None:
    place = seance.places["A1"]
    annule = await base.inserer_billet(seance.id, place, statut="ANNULE")
    billets = [_billet(seance.id, place, uuid.uuid4()) for _ in range(INSERTIONS_SIMULTANEES)]

    insertions = await _insertions_simultanees(database_url, billets, outils)

    refus = Counter(_contrainte(i.erreur) for i in insertions)
    assert refus == {"uq_billets_place": INSERTIONS_SIMULTANEES}, refus
    lignes = await base.lignes(
        "SELECT id, statut FROM billets WHERE place_id = :place", place=place
    )
    assert [(ligne["id"], ligne["statut"]) for ligne in lignes] == [(annule, "ANNULE")]
