"""CA1 de BIL-012, test dédié : un partenaire ne voit jamais les commandes d'un autre.

Vraie base PostgreSQL, vrai Redis, vrais Billets et Paiements (conftest du service) ; toutes les
commandes sont créées par l'API (`POST /api/v1/orders`), jamais semées. Revendeurs R1 et R2 :
jetons `EmetteurDeTest` (H8, sujets `service-account-revendeur-test` et
`service-account-revendeur-test-2`) ; client direct A (`client.test@exemple.test`).
"""

import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.anyio

TOURS_CONCURRENCE = 10


def _sujet(outils: Any, qui: str) -> str:
    return str(outils.clients[qui]["sujet"])


async def _commandes_de_tous(plateforme: Any, outils: Any) -> dict[str, list[str]]:
    """R1 crée A1 et A2, R2 crée A3, A crée A4 (carte acceptée) ; identifiants par appelant."""
    creees: dict[str, list[str]] = {"R1": [], "R2": [], "A": []}
    for qui, place in (("R1", "A1"), ("R1", "A2"), ("R2", "A3"), ("A", "A4")):
        reponse = await plateforme.commander(qui, [place])
        creees[qui].append(outils.exiger_statut(reponse, 201, f"{qui} commande {place}")["id"])
    return creees


def _sans_identifiant(corps: dict[str, Any], identifiant: str) -> dict[str, Any]:
    """Corps Problem Details sans `correlation_id`, l'identifiant demandé remplacé par `<id>`."""
    return {
        cle: valeur.replace(identifiant, "<id>") if isinstance(valeur, str) else valeur
        for cle, valeur in corps.items()
        if cle != "correlation_id"
    }


async def _commande_en_attente(plateforme: Any, outils: Any, qui: str, place: str) -> str:
    """Commande de `qui` laissée EN_ATTENTE : Paiements injoignable (503), puis rétabli."""
    plateforme.paiements_injoignable()
    reponse = await plateforme.commander(qui, [place])
    outils.exiger_probleme(reponse, 503, "SERVICE_INDISPONIBLE", f"{qui} commande {place}")
    plateforme.retablir()
    (ligne,) = await plateforme.bases.commandes_de(_sujet(outils, qui))
    assert ligne["statut"] == "EN_ATTENTE", ligne
    return str(ligne["id"])


async def test_un_revendeur_ne_liste_que_ses_commandes_jamais_celles_d_un_autre_revendeur_ni_d_un_client_direct(  # noqa: E501
    plateforme: Any, outils: Any
) -> None:
    creees = await _commandes_de_tous(plateforme, outils)

    for qui, attendu in (("R1", 2), ("R2", 1)):
        corps = outils.exiger_statut(await plateforme.lister(qui), 200, f"{qui} liste")
        assert corps["total"] == attendu, (qui, corps)
        assert sorted(c["id"] for c in corps["elements"]) == sorted(creees[qui]), (qui, corps)


async def test_un_client_direct_ne_voit_jamais_les_commandes_des_revendeurs(
    plateforme: Any, outils: Any
) -> None:
    creees = await _commandes_de_tous(plateforme, outils)

    corps = outils.exiger_statut(await plateforme.lister("A"), 200, "A liste")

    assert corps["total"] == 1, corps
    assert [c["id"] for c in corps["elements"]] == creees["A"], corps


@pytest.mark.parametrize(
    ("lecteur", "proprietaire"),
    [("R1", "R2"), ("R1", "A"), ("A", "R1")],
    ids=["R1-lit-R2", "R1-lit-A", "A-lit-R1"],
)
async def test_le_detail_d_une_commande_d_un_autre_revendeur_ou_d_un_client_direct_renvoie_404(
    lecteur: str, proprietaire: str, plateforme: Any, outils: Any
) -> None:
    creees = await _commandes_de_tous(plateforme, outils)
    autre = creees[proprietaire][0]
    inconnu = str(uuid.uuid4())

    reponse = await plateforme.lire(lecteur, autre)
    reference = await plateforme.lire(lecteur, inconnu)

    corps = outils.exiger_probleme(reponse, 404, "ORDER_NOT_FOUND", f"{lecteur} lit {autre}")
    corps_inconnu = outils.exiger_probleme(reference, 404, "ORDER_NOT_FOUND", "UUID inconnu")
    assert _sans_identifiant(corps, autre) == _sans_identifiant(corps_inconnu, inconnu)
    assert _sujet(outils, proprietaire) not in reponse.text


@pytest.mark.parametrize("proprietaire", ["R2", "A"])
async def test_payer_la_commande_d_un_autre_revendeur_ou_d_un_client_direct_renvoie_404_sans_debit(
    proprietaire: str, plateforme: Any, outils: Any
) -> None:
    commande_id = await _commande_en_attente(plateforme, outils, proprietaire, "A5")
    avant = await plateforme.bases.commande(commande_id)
    appels_avant = len(plateforme.gateway.appels_vers("paiements"))

    reponse = await plateforme.payer("R1", commande_id, carte=outils.carte_acceptee)

    outils.exiger_probleme(
        reponse, 404, "ORDER_NOT_FOUND", f"R1 paie la commande de {proprietaire}"
    )
    assert len(plateforme.gateway.appels_vers("paiements")) == appels_avant
    apres = await plateforme.bases.commande(commande_id)
    assert apres["statut"] == "EN_ATTENTE", apres
    assert apres["expire_le"] == avant["expire_le"]
    assert await plateforme.bases.paiements_de(commande_id) == []


async def test_un_parametre_de_requete_ne_change_pas_le_revendeur_appelant(
    plateforme: Any, outils: Any
) -> None:
    creees = await _commandes_de_tous(plateforme, outils)

    reponse = await plateforme.lister(
        "R1",
        client=_sujet(outils, "R2"),
        revendeur=outils.clients["R2"]["client"],
        canal="DIRECT",
    )

    corps = outils.exiger_statut(reponse, 200, "R1 liste avec des paramètres étrangers")
    assert sorted(c["id"] for c in corps["elements"]) == sorted(creees["R1"]), corps
    assert corps["total"] == len(creees["R1"]), corps


async def test_la_meme_idempotency_key_chez_deux_revendeurs_donne_deux_commandes_distinctes(
    plateforme: Any, outils: Any
) -> None:
    premiere = await plateforme.commander("R1", ["A1"], cle="cle-partagee-test")
    seconde = await plateforme.commander("R2", ["A2"], cle="cle-partagee-test")

    corps_r1 = outils.exiger_statut(premiere, 201, "R1, clé partagée")
    corps_r2 = outils.exiger_statut(seconde, 201, "R2, même clé")
    assert corps_r1["id"] != corps_r2["id"]
    assert (await plateforme.bases.commande(corps_r1["id"]))["client"] == _sujet(outils, "R1")
    assert (await plateforme.bases.commande(corps_r2["id"]))["client"] == _sujet(outils, "R2")


@pytest.mark.concurrence
async def test_deux_revendeurs_en_parallele_sur_la_meme_place_un_seul_l_obtient_et_chacun_ne_voit_que_la_sienne(  # noqa: E501
    plateforme: Any, outils: Any
) -> None:
    gagnantes: dict[str, set[str]] = {"R1": set(), "R2": set()}
    for tour in range(TOURS_CONCURRENCE):
        # Nouvelle séance à chaque tour : ni place ni plafond hérités du tour précédent.
        seance = await plateforme.nouvelle_seance()

        async def appel(numero: int, seance: Any = seance) -> Any:
            return await plateforme.commander(
                ("R1", "R2")[numero], ["B1"], seance=seance, instance=plateforme.instance(numero)
            )

        reponses = await outils.barriere(2, appel)

        assert sorted(r.status_code for r in reponses) == [201, 409], (
            tour,
            [r.text for r in reponses],
        )
        for qui, reponse in zip(("R1", "R2"), reponses, strict=True):
            if reponse.status_code == 201:
                assert reponse.json()["statut"] == "CONFIRMEE", (tour, reponse.text)
                gagnantes[qui].add(reponse.json()["id"])
            else:
                assert reponse.json()["code"] == "SEAT_ALREADY_TAKEN", (tour, reponse.text)
        contenant = await plateforme.bases.commandes.lignes(
            "SELECT c.statut FROM commandes c JOIN lignes_commande l ON l.commande_id = c.id"
            " WHERE l.place_id = :place",
            place=seance.places["B1"],
        )
        assert sorted(c["statut"] for c in contenant) == ["CONFIRMEE", "EXPIREE"], (
            tour,
            contenant,
        )

    for qui in ("R1", "R2"):
        en_base = {str(c["id"]) for c in await plateforme.bases.commandes_de(_sujet(outils, qui))}
        corps = outils.exiger_statut(await plateforme.lister(qui, size=100), 200, f"{qui} liste")
        listees = {c["id"] for c in corps["elements"]}
        assert listees == en_base, (qui, listees ^ en_base)
        assert corps["total"] == TOURS_CONCURRENCE, (qui, corps["total"])
        assert gagnantes[qui] <= listees
        autre = "R2" if qui == "R1" else "R1"
        assert not listees & gagnantes[autre], qui
