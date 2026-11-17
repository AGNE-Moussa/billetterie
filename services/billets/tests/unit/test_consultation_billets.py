"""listerBillets et lireBillet (BIL-021 ; Q2, Q3, Q6 de BIL-018).

Scope tickets:read (client et revendeur) ; lecture toujours filtrée par l'appelant du jeton
(`sub`), jamais par un paramètre ; billet d'autrui : 404 TICKET_NOT_FOUND, jamais 403 ; filtre
facultatif `commande_id` (inconnu : 200 vide) ; pagination `page`/`size` (size au plus 100).

Le dépôt SQL est remplacé par `DepotBilletsLectureEnMemoire` (port `DepotBillets`), qui note
chaque appel reçu : on vérifie ainsi que la route lui passe l'appelant du jeton.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from billets.api.dependances import obtenir_depot_billets
from billets.domaine.consultation import BilletLu, DepotBillets, StatutBillet
from billets.domaine.places import PageResultat
from commun.faux_jetons import EmetteurDeTest

pytestmark = pytest.mark.anyio

TICKETS = "/api/v1/tickets"
CLIENT_A = "client-a"
CLIENT_B = "client-b"
REVENDEUR = "sujet-revendeur-test"
SCOPES = ["events:read", "orders:read", "orders:write", "tickets:read"]
EMISSION = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class BilletStocke:
    client: str
    billet: BilletLu


class DepotBilletsLectureEnMemoire:
    """Double du port `DepotBillets` : filtre par client (et commande), tri par émission
    décroissante puis identifiant ; `appels` note (méthode, client, argument)."""

    def __init__(self) -> None:
        self.stock: list[BilletStocke] = []
        self.appels: list[tuple[str, str, Any]] = []

    def semer(
        self, client: str, commande_id: UUID, *, rang: str = "A", numero: int = 1, decalage: int = 0
    ) -> BilletLu:
        billet = BilletLu(
            id=uuid4(),
            commande_id=commande_id,
            seance_id=uuid4(),
            place_id=uuid4(),
            rang=rang,
            numero=numero,
            statut=StatutBillet.EMIS,
            qr_code=f"qr-synthetique-{uuid4()}",
            emis_le=EMISSION + timedelta(minutes=decalage),
        )
        self.stock.append(BilletStocke(client, billet))
        return billet

    async def lister_billets(
        self, client: str, commande_id: UUID | None, page: int, size: int
    ) -> PageResultat[BilletLu]:
        self.appels.append(("lister", client, commande_id))
        retenus = sorted(
            (
                s.billet
                for s in self.stock
                if s.client == client
                and (commande_id is None or s.billet.commande_id == commande_id)
            ),
            key=lambda b: (-b.emis_le.timestamp(), str(b.id)),
        )
        debut = (page - 1) * size
        return PageResultat(elements=retenus[debut : debut + size], total=len(retenus))

    async def lire_billet(self, client: str, billet_id: UUID) -> BilletLu | None:
        self.appels.append(("lire", client, billet_id))
        return next(
            (s.billet for s in self.stock if s.client == client and s.billet.id == billet_id),
            None,
        )


@pytest.fixture
def depot_lecture() -> DepotBilletsLectureEnMemoire:
    return DepotBilletsLectureEnMemoire()


@pytest.fixture
def app(fabrique_app: Any, depot_lecture: DepotBilletsLectureEnMemoire) -> FastAPI:
    application: FastAPI = fabrique_app()

    def depot_de_test() -> DepotBillets:
        return depot_lecture

    application.dependency_overrides[obtenir_depot_billets] = depot_de_test
    return application


@pytest.fixture
def entetes_a(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(sujet=CLIENT_A, roles=["customer"], scopes=SCOPES)


@pytest.fixture
def entetes_b(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(sujet=CLIENT_B, roles=["customer"], scopes=SCOPES)


@pytest.fixture
def entetes_r(emetteur: EmetteurDeTest) -> dict[str, str]:
    return emetteur.entetes(
        sujet=REVENDEUR, roles=["partner"], scopes=SCOPES, client="revendeur-test"
    )


def _assert_probleme(reponse: httpx.Response, statut: int, code: str) -> None:
    assert reponse.status_code == statut, reponse.text
    assert reponse.headers["content-type"] == "application/problem+json"
    assert reponse.json()["code"] == code


# --- listerBillets ------------------------------------------------------------------------------


async def test_la_liste_ne_contient_que_les_billets_de_l_appelant(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_a: dict[str, str],
) -> None:
    mien = depot_lecture.semer(CLIENT_A, uuid4(), rang="B", numero=7)
    depot_lecture.semer(CLIENT_B, uuid4())

    reponse = await client.get(TICKETS, headers=entetes_a)

    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == {
        "elements": [
            {
                "id": str(mien.id),
                "commande_id": str(mien.commande_id),
                "seance_id": str(mien.seance_id),
                "place_id": str(mien.place_id),
                "rang": "B",
                "numero": 7,
                "statut": "EMIS",
                "qr_code": mien.qr_code,
                "emis_le": mien.emis_le.isoformat().replace("+00:00", "Z"),
            }
        ],
        "page": 1,
        "size": 20,
        "total": 1,
    }
    assert depot_lecture.appels == [("lister", CLIENT_A, None)]


@pytest.mark.parametrize("parametre", ["client", "client_id", "sub", "revendeur"])
async def test_un_parametre_designant_un_autre_client_est_ignore(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_a: dict[str, str],
    parametre: str,
) -> None:
    depot_lecture.semer(CLIENT_B, uuid4())

    reponse = await client.get(TICKETS, params={parametre: CLIENT_B}, headers=entetes_a)

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["elements"] == []
    assert depot_lecture.appels == [("lister", CLIENT_A, None)]


async def test_le_filtre_commande_id_restreint_aux_billets_de_cette_commande(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_a: dict[str, str],
) -> None:
    commande = uuid4()
    premier = depot_lecture.semer(CLIENT_A, commande, numero=1)
    second = depot_lecture.semer(CLIENT_A, commande, numero=2, decalage=1)
    depot_lecture.semer(CLIENT_A, uuid4())

    reponse = await client.get(TICKETS, params={"commande_id": str(commande)}, headers=entetes_a)

    assert reponse.status_code == 200, reponse.text
    assert [b["id"] for b in reponse.json()["elements"]] == [str(second.id), str(premier.id)]
    assert reponse.json()["total"] == 2
    assert depot_lecture.appels == [("lister", CLIENT_A, commande)]


@pytest.mark.parametrize("cas", ["inconnue", "d_un_autre_client"])
async def test_une_commande_inconnue_ou_d_autrui_donne_une_liste_vide(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_a: dict[str, str],
    cas: str,
) -> None:
    commande = uuid4()
    if cas == "d_un_autre_client":
        depot_lecture.semer(CLIENT_B, commande)

    reponse = await client.get(TICKETS, params={"commande_id": str(commande)}, headers=entetes_a)

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["elements"] == []
    assert reponse.json()["total"] == 0


async def test_un_commande_id_invalide_renvoie_422(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_a: dict[str, str],
) -> None:
    reponse = await client.get(TICKETS, params={"commande_id": "pas-un-uuid"}, headers=entetes_a)

    _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert depot_lecture.appels == []


async def test_la_pagination_decoupe_les_billets_et_garde_le_total(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_a: dict[str, str],
) -> None:
    for numero in range(1, 6):
        depot_lecture.semer(CLIENT_A, uuid4(), numero=numero, decalage=numero)

    reponse = await client.get(TICKETS, params={"page": 2, "size": 2}, headers=entetes_a)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert (corps["page"], corps["size"], corps["total"]) == (2, 2, 5)
    assert [b["numero"] for b in corps["elements"]] == [3, 2]


@pytest.mark.parametrize("params", [{"page": 0}, {"size": 0}, {"size": 101}, {"page": "x"}])
async def test_une_pagination_invalide_renvoie_422(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_a: dict[str, str],
    params: dict[str, Any],
) -> None:
    reponse = await client.get(TICKETS, params=params, headers=entetes_a)

    _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert depot_lecture.appels == []


async def test_un_revendeur_liste_ses_propres_billets(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_r: dict[str, str],
) -> None:
    sien = depot_lecture.semer(REVENDEUR, uuid4())
    depot_lecture.semer(CLIENT_A, uuid4())

    reponse = await client.get(TICKETS, headers=entetes_r)

    assert reponse.status_code == 200, reponse.text
    assert [b["id"] for b in reponse.json()["elements"]] == [str(sien.id)]


# --- lireBillet ---------------------------------------------------------------------------------


async def test_l_appelant_lit_son_billet_avec_son_qr_code(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_a: dict[str, str],
) -> None:
    billet = depot_lecture.semer(CLIENT_A, uuid4(), rang="C", numero=3)

    reponse = await client.get(f"{TICKETS}/{billet.id}", headers=entetes_a)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert (corps["id"], corps["rang"], corps["numero"], corps["qr_code"]) == (
        str(billet.id),
        "C",
        3,
        billet.qr_code,
    )
    assert corps["statut"] == StatutBillet.EMIS.value
    assert depot_lecture.appels == [("lire", CLIENT_A, billet.id)]


@pytest.mark.parametrize("cas", ["d_un_autre_client", "inexistant"])
async def test_un_billet_d_autrui_ou_inexistant_renvoie_404_ticket_not_found(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_a: dict[str, str],
    cas: str,
) -> None:
    billet_id = depot_lecture.semer(CLIENT_B, uuid4()).id if cas == "d_un_autre_client" else uuid4()

    reponse = await client.get(f"{TICKETS}/{billet_id}", headers=entetes_a)

    _assert_probleme(reponse, 404, "TICKET_NOT_FOUND")
    assert depot_lecture.appels == [("lire", CLIENT_A, billet_id)]


async def test_un_identifiant_de_billet_invalide_renvoie_422(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    entetes_a: dict[str, str],
) -> None:
    reponse = await client.get(f"{TICKETS}/pas-un-uuid", headers=entetes_a)

    _assert_probleme(reponse, 422, "REQUETE_INVALIDE")
    assert depot_lecture.appels == []


# --- Accès ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["lister", "lire"])
async def test_sans_jeton_les_billets_renvoient_401(
    client: httpx.AsyncClient, depot_lecture: DepotBilletsLectureEnMemoire, route: str
) -> None:
    chemin = TICKETS if route == "lister" else f"{TICKETS}/{uuid4()}"

    reponse = await client.get(chemin)

    _assert_probleme(reponse, 401, "JETON_ABSENT")
    assert depot_lecture.appels == []


@pytest.mark.parametrize("route", ["lister", "lire"])
@pytest.mark.parametrize("appelant", ["sans_tickets_read", "admin", "service"])
async def test_sans_scope_tickets_read_les_billets_renvoient_403(
    client: httpx.AsyncClient,
    depot_lecture: DepotBilletsLectureEnMemoire,
    emetteur: EmetteurDeTest,
    route: str,
    appelant: str,
) -> None:
    entetes = {
        "sans_tickets_read": emetteur.entetes(
            sujet=CLIENT_A, roles=["customer"], scopes=["events:read", "orders:read"]
        ),
        "admin": emetteur.entetes(roles=["admin"], scopes=["events:read", "events:write"]),
        "service": emetteur.entetes(client="services", scopes=["seats:lock"]),
    }[appelant]
    chemin = TICKETS if route == "lister" else f"{TICKETS}/{uuid4()}"

    reponse = await client.get(chemin, headers=entetes)

    _assert_probleme(reponse, 403, "SCOPE_MANQUANT")
    assert depot_lecture.appels == []
