"""Cache des lectures : une création admin est visible aussitôt (CA1) et invalide seulement
les familles de listes concernées (E2, décision D8 ; questions Q12 à Q15 du plan BIL-005).

« La copie de secours a disparu » se vérifie de l'extérieur : base coupée, la même lecture
répond 503 au lieu de 200 X-Cache-Stale.
"""

from datetime import timedelta
from typing import Any
from uuid import uuid4

import anyio
import httpx
import pytest

from catalogue.api.routes import EN_TETE_CACHE_PERIME

pytestmark = pytest.mark.anyio

ROUTE_EVENEMENTS = "/api/v1/events"
ROUTE_LIEUX = "/api/v1/venues"
# Au-delà de la fraîcheur par défaut (30 s, décision D7) : seule la copie de secours reste.
APRES_FRAICHEUR = 31.0


def _ids(reponse: httpx.Response) -> list[str]:
    return [element["id"] for element in reponse.json()["elements"]]


def _assert_base_indisponible(reponse: httpx.Response) -> None:
    assert reponse.status_code == 503, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == "BASE_INDISPONIBLE"
    assert EN_TETE_CACHE_PERIME not in reponse.headers


def _assert_secours(reponse: httpx.Response) -> None:
    assert reponse.status_code == 200, reponse.text
    assert reponse.headers.get_list(EN_TETE_CACHE_PERIME) == ["true"]


# --- CA1 : une modification admin est visible immédiatement ----------------------------------


async def test_un_evenement_cree_apparait_aussitot_dans_la_liste_deja_en_cache(
    client: httpx.AsyncClient,
    depot: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    evenement_valide: dict[str, str],
) -> None:
    depot.semer_evenement()
    await en_cache(ROUTE_EVENEMENTS)

    cree = await client.post(ROUTE_EVENEMENTS, json=evenement_valide, headers=entetes_admin)
    reponse = await client.get(ROUTE_EVENEMENTS)

    assert cree.status_code == 201, cree.text
    assert reponse.status_code == 200
    assert reponse.json()["total"] == 2
    assert cree.json()["id"] in _ids(reponse)
    assert EN_TETE_CACHE_PERIME not in reponse.headers


async def test_un_lieu_cree_apparait_aussitot_dans_la_liste_des_lieux_deja_en_cache(
    client: httpx.AsyncClient,
    depot: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    lieu_valide: dict[str, str],
) -> None:
    depot.semer_lieu()
    await en_cache(ROUTE_LIEUX)

    cree = await client.post(ROUTE_LIEUX, json=lieu_valide, headers=entetes_admin)
    reponse = await client.get(ROUTE_LIEUX)

    assert cree.status_code == 201, cree.text
    assert reponse.json()["total"] == 2
    assert cree.json()["id"] in _ids(reponse)


async def test_une_seance_programmee_apparait_aussitot_dans_les_seances_deja_en_cache(
    client: httpx.AsyncClient,
    semis: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    seance_valide: Any,
) -> None:
    chemin = semis.lectures["listerSeances"]
    await en_cache(chemin)

    cree = await client.post(chemin, json=seance_valide(semis.lieu.id), headers=entetes_admin)
    reponse = await client.get(chemin)

    assert cree.status_code == 201, cree.text
    assert reponse.json()["total"] == 2
    assert cree.json()["id"] in _ids(reponse)


async def test_une_seance_programmee_apparait_aussitot_dans_la_recherche_par_ville_deja_en_cache(
    client: httpx.AsyncClient,
    depot: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    seance_valide: Any,
) -> None:
    evenement = depot.semer_evenement()
    lieu = depot.semer_lieu(ville="Villetest")
    recherche = f"{ROUTE_EVENEMENTS}?ville=Villetest"
    en_cache_avant = await en_cache(recherche)
    assert en_cache_avant.json()["total"] == 0

    cree = await client.post(
        f"{ROUTE_EVENEMENTS}/{evenement.id}/shows",
        json=seance_valide(lieu.id),
        headers=entetes_admin,
    )
    reponse = await client.get(recherche)

    assert cree.status_code == 201, cree.text
    assert reponse.json()["total"] == 1
    assert _ids(reponse) == [str(evenement.id)]


async def test_une_lecture_commencee_avant_une_creation_ne_remet_pas_l_ancienne_liste_en_cache(
    client: httpx.AsyncClient,
    depot: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    evenement_valide: dict[str, str],
) -> None:
    # Q14 : la lecture L manque le cache et lit l'ancienne liste ; la création C valide et
    # invalide ; L, débloquée ensuite, ne doit pas laisser l'ancienne liste en cache.
    depot.semer_evenement()
    depot.bloquer_listes = anyio.Event()
    depot.liste_commencee = anyio.Event()
    reponses: dict[str, httpx.Response] = {}

    async def lecture() -> None:
        reponses["L"] = await client.get(ROUTE_EVENEMENTS)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as groupe:
            groupe.start_soon(lecture)
            await depot.liste_commencee.wait()
            cree = await client.post(ROUTE_EVENEMENTS, json=evenement_valide, headers=entetes_admin)
            depot.bloquer_listes.set()

    assert reponses["L"].status_code == 200
    assert cree.status_code == 201, cree.text
    # Le GET suivant, puis sa copie servie du cache, contiennent le nouvel événement.
    servie_du_cache = await en_cache(ROUTE_EVENEMENTS)
    assert cree.json()["id"] in _ids(servie_du_cache)


# --- E2 : invalidation à chaque modification admin (D8) ---------------------------------------


async def test_creer_un_evenement_supprime_les_deux_copies_des_listes_d_evenements(
    client: httpx.AsyncClient,
    depot: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    evenement_valide: dict[str, str],
) -> None:
    depot.semer_evenement()
    depot.semer_evenement(nom="Concert de test bis")
    chemins = [
        ROUTE_EVENEMENTS,
        f"{ROUTE_EVENEMENTS}?q=Concert",
        f"{ROUTE_EVENEMENTS}?page=2&size=1",
    ]
    for chemin in chemins:
        await en_cache(chemin)

    cree = await client.post(ROUTE_EVENEMENTS, json=evenement_valide, headers=entetes_admin)
    assert cree.status_code == 201, cree.text
    depot.injoignable = True

    for chemin in chemins:
        _assert_base_indisponible(await client.get(chemin))


async def test_creer_un_lieu_supprime_les_deux_copies_des_listes_de_lieux(
    client: httpx.AsyncClient,
    depot: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    lieu_valide: dict[str, str],
) -> None:
    depot.semer_lieu()
    depot.semer_lieu(nom="Salle de test bis")
    chemins = [ROUTE_LIEUX, f"{ROUTE_LIEUX}?page=2&size=1"]
    for chemin in chemins:
        await en_cache(chemin)

    cree = await client.post(ROUTE_LIEUX, json=lieu_valide, headers=entetes_admin)
    assert cree.status_code == 201, cree.text
    depot.injoignable = True

    for chemin in chemins:
        _assert_base_indisponible(await client.get(chemin))


async def test_programmer_une_seance_supprime_les_deux_copies_des_seances_de_l_evenement(
    client: httpx.AsyncClient,
    depot: Any,
    semis: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    seance_valide: Any,
    maintenant: Any,
) -> None:
    depot.semer_seance(semis.evenement, semis.lieu, maintenant + timedelta(days=40))
    route = semis.lectures["listerSeances"]
    chemins = [f"{route}?page=1&size=1", f"{route}?page=2&size=1"]
    for chemin in chemins:
        await en_cache(chemin)

    cree = await client.post(route, json=seance_valide(semis.lieu.id), headers=entetes_admin)
    assert cree.status_code == 201, cree.text
    depot.injoignable = True

    for chemin in chemins:
        _assert_base_indisponible(await client.get(chemin))


async def test_programmer_une_seance_supprime_les_deux_copies_des_listes_d_evenements(
    client: httpx.AsyncClient,
    depot: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    seance_valide: Any,
) -> None:
    evenement = depot.semer_evenement()
    lieu = depot.semer_lieu(ville="Villetest")
    chemins = [ROUTE_EVENEMENTS, f"{ROUTE_EVENEMENTS}?ville=Villetest"]
    for chemin in chemins:
        await en_cache(chemin)

    cree = await client.post(
        f"{ROUTE_EVENEMENTS}/{evenement.id}/shows",
        json=seance_valide(lieu.id),
        headers=entetes_admin,
    )
    assert cree.status_code == 201, cree.text
    depot.injoignable = True

    for chemin in chemins:
        _assert_base_indisponible(await client.get(chemin))


async def test_creer_un_lieu_ne_touche_ni_aux_evenements_ni_aux_seances(
    client: httpx.AsyncClient,
    depot: Any,
    cache: Any,
    semis: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    lieu_valide: dict[str, str],
) -> None:
    chemins = [
        semis.lectures[operation]
        for operation in (
            "listerEvenements",
            "lireEvenement",
            "listerSeances",
            "lireSeanceParId",
            "lireLieu",
        )
    ]
    for chemin in chemins:
        await en_cache(chemin)

    cree = await client.post(ROUTE_LIEUX, json=lieu_valide, headers=entetes_admin)
    assert cree.status_code == 201, cree.text
    cache.avancer(APRES_FRAICHEUR)
    depot.injoignable = True

    for chemin in chemins:
        _assert_secours(await client.get(chemin))


async def test_creer_un_evenement_ne_touche_ni_aux_lieux_ni_aux_details(
    client: httpx.AsyncClient,
    depot: Any,
    cache: Any,
    semis: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    evenement_valide: dict[str, str],
) -> None:
    chemins = [
        semis.lectures[operation]
        for operation in ("listerLieux", "lireLieu", "lireEvenement", "lireSeance")
    ]
    for chemin in chemins:
        await en_cache(chemin)

    cree = await client.post(ROUTE_EVENEMENTS, json=evenement_valide, headers=entetes_admin)
    assert cree.status_code == 201, cree.text
    cache.avancer(APRES_FRAICHEUR)
    depot.injoignable = True

    for chemin in chemins:
        _assert_secours(await client.get(chemin))


async def test_programmer_une_seance_ne_touche_ni_aux_details_ni_aux_seances_d_un_autre_evenement(
    client: httpx.AsyncClient,
    depot: Any,
    cache: Any,
    semis: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    seance_valide: Any,
) -> None:
    autre = depot.semer_evenement(nom="Autre concert de test")
    chemins = [
        semis.lectures["lireEvenement"],
        semis.lectures["lireLieu"],
        semis.lectures["lireSeanceParId"],
        f"{ROUTE_EVENEMENTS}/{autre.id}/shows",
    ]
    for chemin in chemins:
        await en_cache(chemin)

    cree = await client.post(
        semis.lectures["listerSeances"], json=seance_valide(semis.lieu.id), headers=entetes_admin
    )
    assert cree.status_code == 201, cree.text
    cache.avancer(APRES_FRAICHEUR)
    depot.injoignable = True

    for chemin in chemins:
        _assert_secours(await client.get(chemin))


async def test_une_ecriture_refusee_ne_supprime_aucune_copie(
    client: httpx.AsyncClient,
    depot: Any,
    cache: Any,
    semis: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    entetes_client: dict[str, str],
    evenement_valide: dict[str, str],
    seance_valide: Any,
    maintenant: Any,
) -> None:
    seances = semis.lectures["listerSeances"]
    chemins = [ROUTE_EVENEMENTS, seances]
    for chemin in chemins:
        await en_cache(chemin)

    sans_jeton = await client.post(ROUTE_EVENEMENTS, json=evenement_valide)
    sans_scope = await client.post(ROUTE_EVENEMENTS, json=evenement_valide, headers=entetes_client)
    corps_invalide = await client.post(ROUTE_EVENEMENTS, json={}, headers=entetes_admin)
    evenement_inconnu = await client.post(
        f"{ROUTE_EVENEMENTS}/{uuid4()}/shows",
        json=seance_valide(semis.lieu.id),
        headers=entetes_admin,
    )
    dans_le_passe = await client.post(
        seances,
        json=seance_valide(semis.lieu.id, maintenant - timedelta(days=1)),
        headers=entetes_admin,
    )
    assert sans_jeton.status_code == 401
    assert sans_scope.status_code == 403
    assert corps_invalide.status_code == 422
    assert evenement_inconnu.status_code == 404
    assert dans_le_passe.status_code == 422
    assert dans_le_passe.json()["code"] == "SHOW_START_IN_PAST"

    cache.avancer(APRES_FRAICHEUR)
    depot.injoignable = True

    for chemin in chemins:
        _assert_secours(await client.get(chemin))


async def test_une_ecriture_en_503_base_injoignable_garde_les_copies_de_secours(
    client: httpx.AsyncClient,
    depot: Any,
    cache: Any,
    en_cache: Any,
    entetes_admin: dict[str, str],
    evenement_valide: dict[str, str],
) -> None:
    depot.semer_evenement()
    await en_cache(ROUTE_EVENEMENTS)
    cache.avancer(APRES_FRAICHEUR)
    depot.injoignable = True

    ecriture = await client.post(ROUTE_EVENEMENTS, json=evenement_valide, headers=entetes_admin)
    lecture = await client.get(ROUTE_EVENEMENTS)

    _assert_base_indisponible(ecriture)
    _assert_secours(lecture)
