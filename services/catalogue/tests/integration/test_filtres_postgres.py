"""E3 (BIL-004) : filtres `q`, `ville`, `du` et `au` de `GET /api/v1/events` sur la vraie base.

Jeu commun (plan, section E3) créé par l'API avec le jeton admin, au début de chaque test :
- « Concert de test » : séances à Villetest (J+10) et à Autreville (J+40) ;
- « Théâtre synthétique » (description « Une pièce de test ») : séance à Autreville (J+20) ;
- « Exposition sans séance » : aucune séance.

Décisions appliquées : Q6 (`q` en sous-chaîne insensible à la casse, nom et description), Q7
(`ville` en égalité insensible à la casse), bornes `du` et `au` incluses (contrat).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.anyio

CONCERT = "Concert de test"
THEATRE = "Théâtre synthétique"
EXPOSITION = "Exposition sans séance"


@dataclass
class JeuCommun:
    maintenant: datetime
    debuts: dict[int, datetime]  # jour relatif -> début exact de la séance

    def jour(self, jours: int) -> str:
        return (self.maintenant + timedelta(days=jours)).isoformat()


CreerJeu = Callable[[], Awaitable[JeuCommun]]


@pytest.fixture
def creer_jeu(catalogue: Any) -> CreerJeu:
    """Crée le jeu commun dans le test (une création refusée y échoue par assertion)."""

    async def creer() -> JeuCommun:
        maintenant = catalogue.instant(0)
        villetest = (await catalogue.lieu(nom="Salle de test", ville="Villetest"))["id"]
        autreville = (await catalogue.lieu(nom="Autre salle de test", ville="Autreville"))["id"]
        concert = await catalogue.evenement(nom=CONCERT, description="Description synthétique")
        theatre = await catalogue.evenement(nom=THEATRE, description="Une pièce de test")
        await catalogue.evenement(nom=EXPOSITION, description="Description synthétique")
        debuts = {jours: catalogue.instant(jours) for jours in (10, 20, 40)}
        await catalogue.seance(concert["id"], villetest, debut=debuts[10])
        await catalogue.seance(concert["id"], autreville, debut=debuts[40])
        await catalogue.seance(theatre["id"], autreville, debut=debuts[20])
        return JeuCommun(maintenant, debuts)

    return creer


async def _rechercher(client: httpx.AsyncClient, **filtres: Any) -> dict[str, Any]:
    reponse = await client.get("/api/v1/events", params=filtres)
    assert reponse.status_code == 200, f"{filtres} : {reponse.status_code} {reponse.text}"
    corps: dict[str, Any] = reponse.json()
    return corps


def _noms(page: dict[str, Any]) -> list[str]:
    return [element["nom"] for element in page["elements"]]


async def test_sans_filtre_tous_les_evenements_sont_listes(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    await creer_jeu()

    page = await _rechercher(client_public)

    assert page["total"] == 3
    assert sorted(_noms(page)) == sorted([CONCERT, THEATRE, EXPOSITION])


async def test_q_cherche_dans_le_nom_et_la_description(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    await creer_jeu()

    par_nom = await _rechercher(client_public, q="Concert")
    par_description = await _rechercher(client_public, q="pièce")

    assert _noms(par_nom) == [CONCERT]
    assert _noms(par_description) == [THEATRE]


async def test_q_suit_la_regle_de_casse_retenue(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    await creer_jeu()

    page = await _rechercher(client_public, q="concert")

    # Décision Q6 : insensible à la casse.
    assert _noms(page) == [CONCERT]


async def test_ville_retient_les_evenements_ayant_une_seance_dans_la_ville(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    await creer_jeu()

    page = await _rechercher(client_public, ville="Villetest")

    assert page["total"] == 1
    assert _noms(page) == [CONCERT]


async def test_un_evenement_a_plusieurs_seances_n_apparait_qu_une_fois(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    jeu = await creer_jeu()

    par_ville = await _rechercher(client_public, ville="Autreville")
    par_intervalle = await _rechercher(client_public, du=jeu.jour(0), au=jeu.jour(60))

    for page in (par_ville, par_intervalle):
        assert page["total"] == 2
        assert sorted(_noms(page)) == sorted([CONCERT, THEATRE])


async def test_du_et_au_retiennent_les_evenements_ayant_une_seance_dans_l_intervalle(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    jeu = await creer_jeu()

    page = await _rechercher(client_public, du=jeu.jour(15), au=jeu.jour(25))

    assert _noms(page) == [THEATRE]


async def test_les_bornes_du_et_au_sont_incluses(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    jeu = await creer_jeu()
    exact = jeu.debuts[20].isoformat()

    page = await _rechercher(client_public, du=exact, au=exact)

    assert _noms(page) == [THEATRE]


async def test_du_seul_et_au_seul_bornent_un_seul_cote(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    jeu = await creer_jeu()

    apres = await _rechercher(client_public, du=jeu.jour(30))
    avant = await _rechercher(client_public, au=jeu.jour(15))

    assert _noms(apres) == [CONCERT]
    assert _noms(avant) == [CONCERT]


async def test_ville_et_intervalle_s_appliquent_a_la_meme_seance(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    jeu = await creer_jeu()

    page = await _rechercher(client_public, ville="Villetest", du=jeu.jour(30), au=jeu.jour(50))

    assert page["total"] == 0
    assert page["elements"] == []


async def test_les_filtres_se_cumulent_avec_q(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    await creer_jeu()

    trouve = await _rechercher(client_public, q="Concert", ville="Autreville")
    aucun = await _rechercher(client_public, q="Théâtre", ville="Villetest")

    assert _noms(trouve) == [CONCERT]
    assert aucun["total"] == 0


async def test_le_total_compte_les_evenements_filtres_et_non_la_page(
    client_public: httpx.AsyncClient, creer_jeu: CreerJeu
) -> None:
    await creer_jeu()

    page = await _rechercher(client_public, ville="Autreville", size=1)

    assert page["total"] == 2
    assert len(page["elements"]) == 1
