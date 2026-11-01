"""CA2, E2 et E4 (BIL-004) sur une vraie base PostgreSQL migrée par Alembic.

Refus d'écriture sans trace en base, ordre stable des listes entre les pages, lectures des
séances avec leurs catégories et rangs, création d'une séance et de ses lignes en base.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

pytestmark = pytest.mark.anyio


async def _page(client: httpx.AsyncClient, chemin: str, **parametres: Any) -> dict[str, Any]:
    reponse = await client.get(chemin, params=parametres)
    assert reponse.status_code == 200, f"GET {chemin} : {reponse.status_code} {reponse.text}"
    corps: dict[str, Any] = reponse.json()
    return corps


async def _tous_par_pages(client: httpx.AsyncClient, chemin: str, taille: int) -> list[str]:
    """Identifiants lus page après page (`size` = taille) jusqu'à la page vide."""
    identifiants: list[str] = []
    numero = 1
    while True:
        page = await _page(client, chemin, page=numero, size=taille)
        if not page["elements"]:
            return identifiants
        identifiants += [element["id"] for element in page["elements"]]
        numero += 1


def _cle_creation(element: dict[str, Any]) -> tuple[datetime, UUID]:
    return datetime.fromisoformat(element["cree_le"]), UUID(element["id"])


# CA2


async def test_un_refus_d_ecriture_ne_laisse_rien_en_base(
    client_public: httpx.AsyncClient, jetons: Any, catalogue: Any, base: Any
) -> None:
    evenement = await client_public.post(
        "/api/v1/events", json=catalogue.EVENEMENT, headers=jetons.client
    )
    lieu = await client_public.post("/api/v1/venues", json=catalogue.LIEU, headers=jetons.client)

    assert evenement.status_code == 403, evenement.text
    assert lieu.status_code == 403, lieu.text
    assert await base.compter("evenements") == 0
    assert await base.compter("lieux") == 0
    assert await base.compter("outbox") == 0


# E2 : ordre stable et pagination


async def test_les_evenements_sont_tries_par_creation_puis_identifiant(
    client_public: httpx.AsyncClient, catalogue: Any, base: Any
) -> None:
    crees = [await catalogue.evenement(nom=f"Concert de test {n}") for n in range(1, 4)]
    # Deux événements au même instant, insérés directement : le tri départage par identifiant.
    meme_instant = datetime.fromisoformat(crees[-1]["cree_le"]) + timedelta(seconds=1)
    for n in (4, 5):
        identifiant = uuid4()
        await base.executer(
            "INSERT INTO evenements (id, nom, description, cree_le)"
            " VALUES (:id, :nom, 'Description synthétique', :cree_le)",
            id=identifiant,
            nom=f"Concert de test {n}",
            cree_le=meme_instant,
        )
        crees.append({"id": str(identifiant), "cree_le": meme_instant.isoformat()})
    attendus = [element["id"] for element in sorted(crees, key=_cle_creation)]

    lus = await _tous_par_pages(client_public, "/api/v1/events", taille=2)

    assert lus == attendus
    assert len(set(lus)) == len(lus) == 5


async def test_les_lieux_sont_tries_par_creation_puis_identifiant(
    client_public: httpx.AsyncClient, catalogue: Any, base: Any
) -> None:
    crees = [await catalogue.lieu(nom=f"Salle de test {n}") for n in range(1, 4)]
    meme_instant = datetime.fromisoformat(crees[-1]["cree_le"]) + timedelta(seconds=1)
    for n in (4, 5):
        identifiant = uuid4()
        await base.executer(
            "INSERT INTO lieux (id, nom, adresse, ville, cree_le)"
            " VALUES (:id, :nom, '1 rue de l''Exemple', 'Villetest', :cree_le)",
            id=identifiant,
            nom=f"Salle de test {n}",
            cree_le=meme_instant,
        )
        crees.append({"id": str(identifiant), "cree_le": meme_instant.isoformat()})
    attendus = [element["id"] for element in sorted(crees, key=_cle_creation)]

    lus = await _tous_par_pages(client_public, "/api/v1/venues", taille=2)

    assert lus == attendus
    assert len(set(lus)) == len(lus) == 5


async def test_les_seances_sont_triees_par_debut_puis_identifiant(
    client_public: httpx.AsyncClient, catalogue: Any
) -> None:
    evenement_id = (await catalogue.evenement())["id"]
    lieu_id = (await catalogue.lieu())["id"]
    crees = [
        await catalogue.seance(evenement_id, lieu_id, debut=debut)
        for debut in (
            catalogue.instant(40),
            catalogue.instant(10),
            catalogue.instant(20),
            catalogue.instant(10),
        )
    ]
    attendus = [
        s["id"]
        for s in sorted(crees, key=lambda s: (datetime.fromisoformat(s["debut"]), UUID(s["id"])))
    ]

    page = await _page(client_public, f"/api/v1/events/{evenement_id}/shows")

    assert page["total"] == 4
    assert [element["id"] for element in page["elements"]] == attendus


async def test_les_seances_d_un_evenement_ne_montrent_pas_celles_d_un_autre(
    client_public: httpx.AsyncClient, catalogue: Any
) -> None:
    lieu_id = (await catalogue.lieu())["id"]
    premier = (await catalogue.evenement(nom="Concert de test 1"))["id"]
    second = (await catalogue.evenement(nom="Concert de test 2"))["id"]
    siennes = {
        (await catalogue.seance(premier, lieu_id, debut=catalogue.instant(jours)))["id"]
        for jours in (10, 20)
    }
    for jours in (15, 25):
        await catalogue.seance(second, lieu_id, debut=catalogue.instant(jours))

    page = await _page(client_public, f"/api/v1/events/{premier}/shows")

    assert page["total"] == 2
    assert {element["id"] for element in page["elements"]} == siennes


@pytest.mark.parametrize("lecture", ["lireSeance", "lireSeanceParId", "listerSeances"])
async def test_une_seance_se_lit_avec_ses_categories_et_ses_rangs(
    lecture: str, client_public: httpx.AsyncClient, catalogue: Any
) -> None:
    evenement_id = (await catalogue.evenement())["id"]
    lieu_id = (await catalogue.lieu())["id"]
    debut = catalogue.instant(30)
    creee = await catalogue.seance(evenement_id, lieu_id, debut=debut)
    seance_id = creee["id"]

    if lecture == "lireSeance":
        lue = await _page(client_public, f"/api/v1/events/{evenement_id}/shows/{seance_id}")
    elif lecture == "lireSeanceParId":
        lue = await _page(client_public, f"/api/v1/shows/{seance_id}")
    else:
        page = await _page(client_public, f"/api/v1/events/{evenement_id}/shows")
        assert [element["id"] for element in page["elements"]] == [seance_id]
        lue = page["elements"][0]

    assert lue["id"] == seance_id
    assert lue["evenement_id"] == evenement_id
    assert lue["lieu_id"] == lieu_id
    assert datetime.fromisoformat(lue["debut"]) == debut
    assert lue["annulee"] is False
    assert len(lue["categories"]) == 1
    categorie = lue["categories"][0]
    assert categorie["id"] == creee["categories"][0]["id"]
    assert categorie["nom"] == "Fosse"
    assert categorie["prix"] == 4500
    # Ordre de la requête (décision Q14).
    assert categorie["rangs"] == [
        {"rang": "A", "nombre_places": 10},
        {"rang": "B", "nombre_places": 12},
    ]


# Ordre de la requête, ni alphabétique, ni inverse, ni inverse de l'alphabétique (décision I1).
CATEGORIES_DESORDONNEES = [
    {
        "nom": nom,
        "prix": prix,
        "rangs": [{"rang": rang, "nombre_places": places} for rang, places in rangs],
    }
    for nom, prix, rangs in (
        ("Fosse", 4500, (("C", 10), ("A", 11), ("B", 12))),
        ("Balcon", 3000, (("F", 13), ("D", 14), ("E", 15))),
        ("Carré", 6000, (("I", 16), ("G", 17), ("H", 18))),
    )
]


def _ordre(categories: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    return [(c["nom"], [r["rang"] for r in c["rangs"]]) for c in categories]


@pytest.mark.parametrize("lecture", ["lireSeance", "lireSeanceParId", "listerSeances"])
async def test_l_ordre_des_categories_et_des_rangs_ne_depend_pas_de_l_ordre_physique(
    lecture: str, client_public: httpx.AsyncClient, catalogue: Any, base: Any
) -> None:
    evenement_id = (await catalogue.evenement())["id"]
    lieu_id = (await catalogue.lieu())["id"]
    seance_id = (await catalogue.seance(evenement_id, lieu_id, categories=CATEGORIES_DESORDONNEES))[
        "id"
    ]
    attendu = _ordre(CATEGORIES_DESORDONNEES)
    # Mises à jour sans effet métier, de la dernière ligne à la première : chaque UPDATE écrit
    # une nouvelle version du tuple (nouveau ctid), l'ordre physique devient l'inverse.
    for categorie in reversed(CATEGORIES_DESORDONNEES):
        for rang in reversed(categorie["rangs"]):
            await base.executer(
                "UPDATE rangs SET nombre_places = nombre_places"
                " WHERE seance_id = :seance AND rang = :rang",
                seance=UUID(seance_id),
                rang=rang["rang"],
            )
        await base.executer(
            "UPDATE categories SET prix = prix WHERE seance_id = :seance AND nom = :nom",
            seance=UUID(seance_id),
            nom=categorie["nom"],
        )
    physiques = await base.lignes(
        "SELECT nom FROM categories WHERE seance_id = :seance ORDER BY ctid",
        seance=UUID(seance_id),
    )
    assert [ligne["nom"] for ligne in physiques] != [nom for nom, _ in attendu], (
        "précondition : les UPDATE n'ont pas changé l'ordre physique"
    )

    if lecture == "lireSeance":
        lue = await _page(client_public, f"/api/v1/events/{evenement_id}/shows/{seance_id}")
    elif lecture == "lireSeanceParId":
        lue = await _page(client_public, f"/api/v1/shows/{seance_id}")
    else:
        page = await _page(client_public, f"/api/v1/events/{evenement_id}/shows")
        lue = page["elements"][0]

    assert _ordre(lue["categories"]) == attendu


async def test_un_lieu_cree_se_relit(client_public: httpx.AsyncClient, catalogue: Any) -> None:
    cree = await catalogue.lieu()

    lu = await _page(client_public, f"/api/v1/venues/{cree['id']}")

    assert lu["nom"] == "Salle de test"
    assert lu["adresse"] == "1 rue de l'Exemple"
    assert lu["ville"] == "Villetest"
    assert datetime.fromisoformat(lu["cree_le"]) == datetime.fromisoformat(cree["cree_le"])


# E4 : créations admin


async def test_un_admin_programme_une_seance_avec_ses_categories(
    client_admin: httpx.AsyncClient, catalogue: Any, base: Any
) -> None:
    evenement_id = (await catalogue.evenement())["id"]
    lieu_id = (await catalogue.lieu())["id"]

    reponse = await client_admin.post(
        f"/api/v1/events/{evenement_id}/shows", json=catalogue.corps_seance(lieu_id)
    )

    assert reponse.status_code == 201, reponse.text
    seance = reponse.json()
    assert seance["annulee"] is False
    assert seance["evenement_id"] == evenement_id
    assert seance["lieu_id"] == lieu_id
    assert [(c["nom"], c["prix"], c["rangs"]) for c in seance["categories"]] == [
        (c["nom"], c["prix"], c["rangs"]) for c in catalogue.CATEGORIES
    ]
    assert await base.compter("seances") == 1
    assert await base.compter("categories") == 1
    rangs = await base.lignes("SELECT rang, categorie_id FROM rangs ORDER BY rang")
    assert [ligne["rang"] for ligne in rangs] == ["A", "B"]
    assert {str(ligne["categorie_id"]) for ligne in rangs} == {seance["categories"][0]["id"]}


async def test_un_meme_rang_dans_deux_seances_est_accepte(
    client_admin: httpx.AsyncClient, catalogue: Any
) -> None:
    evenement_id = (await catalogue.evenement())["id"]
    lieu_id = (await catalogue.lieu())["id"]
    categories = [{"nom": "Fosse", "prix": 4500, "rangs": [{"rang": "A", "nombre_places": 10}]}]

    reponses = [
        await client_admin.post(
            f"/api/v1/events/{evenement_id}/shows",
            json=catalogue.corps_seance(lieu_id, catalogue.instant(jours), categories),
        )
        for jours in (10, 20)
    ]

    assert [reponse.status_code for reponse in reponses] == [201, 201], [
        reponse.text for reponse in reponses
    ]
