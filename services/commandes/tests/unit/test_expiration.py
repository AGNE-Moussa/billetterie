"""Tâche d'expiration des commandes non payées (plan BIL-010, CA1 « Tâche périodique » et CA2).

Sans base ni Redis : `DepotEnMemoire` (conftest) pour le dépôt, un double de `ClientPaiements`
qui note chaque appel, un double en mémoire du port `VerrouTache`, et l'horloge `MAINTENANT`.
"""

import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import jsonschema
import pytest
from fastapi import FastAPI

from commandes.api.dependances import obtenir_billets, obtenir_paiements
from commandes.domaine.commandes import (
    EVENEMENT_COMMANDE_EXPIREE,
    Commande,
    StatutCommande,
)
from commandes.domaine.expiration import (
    CLE_VERROU_TACHE,
    VerrouTacheIndisponible,
    executer_cycle,
    expirer_commandes_depassees,
)
from commandes.domaine.services import PaiementEnregistre, PaiementLu, VerrouPlace
from commandes.infra.clients import CIBLE_PAIEMENTS
from commun.http import ServiceIndisponible

pytestmark = pytest.mark.anyio

RACINE = Path(__file__).resolve().parents[4]
SCHEMA = RACINE / "docs" / "evenements" / f"{EVENEMENT_COMMANDE_EXPIREE}.json"
LOT = 100
PERIODE = 1.0


# --- Doubles ------------------------------------------------------------------------------------


class PaiementsEspion:
    """Double de `ClientPaiements` : note chaque appel.

    `statuts[commande_id]` : statut lu par `lire` (absent : 404, donc None) ; `injoignable` :
    `lire` lève `ServiceIndisponible`.
    """

    def __init__(self) -> None:
        self.statuts: dict[UUID, str] = {}
        self.injoignable = False
        self.lectures: list[UUID] = []
        self.paiements_postes: list[UUID] = []

    async def payer(
        self, *, commande_id: UUID, seance_id: UUID, montant: int, carte_test: str
    ) -> PaiementEnregistre:
        self.paiements_postes.append(commande_id)
        return PaiementEnregistre(
            id=uuid4(), commande_id=commande_id, seance_id=seance_id, montant=montant
        )

    async def lire(self, commande_id: UUID) -> PaiementLu | None:
        self.lectures.append(commande_id)
        if self.injoignable:
            raise ServiceIndisponible(CIBLE_PAIEMENTS)
        statut = self.statuts.get(commande_id)
        return None if statut is None else PaiementLu(commande_id=commande_id, statut=statut)


class VerrouTacheEnMemoire:
    """Double du port `VerrouTache` : `SET NX PX` sans expiration réelle (un seul cycle testé)."""

    def __init__(self) -> None:
        # clé : (propriétaire, durée en ms)
        self.cles: dict[str, tuple[str, int]] = {}
        self.injoignable = False

    async def prendre(self, cle: str, proprietaire: str, duree_ms: int) -> bool:
        if self.injoignable:
            raise VerrouTacheIndisponible()
        if cle in self.cles:
            return False
        self.cles[cle] = (proprietaire, duree_ms)
        return True

    async def fermer(self) -> None:
        return None


@pytest.fixture
def paiements_espion() -> PaiementsEspion:
    return PaiementsEspion()


@pytest.fixture
def verrou() -> VerrouTacheEnMemoire:
    return VerrouTacheEnMemoire()


@pytest.fixture
def lectures_du_depot(depot: Any, monkeypatch: pytest.MonkeyPatch) -> list[tuple[datetime, int]]:
    """Appels à `lister_a_expirer` du dépôt en mémoire, notés sans changer son résultat."""
    appels: list[tuple[datetime, int]] = []
    original = depot.lister_a_expirer

    async def espion(maintenant: datetime, limite: int) -> list[Commande]:
        appels.append((maintenant, limite))
        resultat: list[Commande] = await original(maintenant, limite)
        return resultat

    monkeypatch.setattr(depot, "lister_a_expirer", espion)
    return appels


# --- Données ------------------------------------------------------------------------------------


def _maintenant(horloge: Any) -> datetime:
    instant: datetime = horloge.maintenant
    return instant


def _semer(
    depot: Any,
    statut: StatutCommande,
    expire_le: datetime | None,
    *,
    lignes: int = 1,
    paiement_demande: bool = False,
    cree_le: datetime | None = None,
) -> Commande:
    """Commande d'un client synthétique, échéance et `paiement_demande` imposés."""
    semee: Commande = depot.semer(
        f"client-test-{uuid4()}",
        uuid4(),
        statut,
        lignes=lignes,
        email="client.test@exemple.test",
        **({} if cree_le is None else {"cree_le": cree_le}),
    )
    commande = replace(semee, expire_le=expire_le, paiement_demande=paiement_demande)
    depot.commandes[commande.id] = commande
    return commande


def _statut(depot: Any, commande: Commande) -> StatutCommande:
    statut: StatutCommande = depot.commandes[commande.id].statut
    return statut


def _expirations(depot: Any) -> list[Any]:
    evenements: list[Any] = depot.evenements_de(EVENEMENT_COMMANDE_EXPIREE)
    return evenements


def _expirations_de(depot: Any, commande: Commande) -> list[Any]:
    return [e for e in _expirations(depot) if e.data["commande_id"] == str(commande.id)]


def _schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return schema


# --- CA1 : sélection, transition, événement ------------------------------------------------------


async def test_la_tache_expire_une_commande_en_attente_dont_l_echeance_est_depassee(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1), lignes=2)

    expirees = await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert expirees == 1
    assert _statut(depot, commande) is StatutCommande.EXPIREE
    assert len(_expirations_de(depot, commande)) == 1


async def test_la_tache_expire_une_commande_dont_l_echeance_est_exactement_maintenant(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(depot, StatutCommande.EN_ATTENTE, maintenant)

    await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert _statut(depot, commande) is StatutCommande.EXPIREE


async def test_la_tache_ignore_une_commande_dont_l_echeance_n_est_pas_atteinte(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(depot, StatutCommande.EN_ATTENTE, maintenant + timedelta(seconds=1))

    expirees = await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert expirees == 0
    assert _statut(depot, commande) is StatutCommande.EN_ATTENTE
    assert _expirations(depot) == []


async def test_la_tache_ignore_les_commandes_confirmees_expirees_ou_remboursees(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    passee = maintenant - timedelta(seconds=1)
    commandes = {
        statut: _semer(depot, statut, passee)
        for statut in (
            StatutCommande.CONFIRMEE,
            StatutCommande.EXPIREE,
            StatutCommande.REMBOURSEE,
        )
    }

    expirees = await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert expirees == 0
    assert {s: _statut(depot, c) for s, c in commandes.items()} == {s: s for s in commandes}
    assert _expirations(depot) == []


async def test_la_tache_ignore_une_commande_sans_echeance(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(
        depot, StatutCommande.EN_ATTENTE, None, cree_le=maintenant - timedelta(hours=1)
    )

    expirees = await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert expirees == 0
    assert _statut(depot, commande) is StatutCommande.EN_ATTENTE
    assert _expirations(depot) == []


async def test_l_evenement_d_expiration_porte_la_commande_la_seance_et_toutes_ses_places(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1), lignes=3)

    await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    evenements = _expirations_de(depot, commande)
    assert len(evenements) == 1
    assert evenements[0].data == {
        "commande_id": str(commande.id),
        "seance_id": str(commande.seance_id),
        "place_ids": [str(ligne.place_id) for ligne in commande.lignes],
    }
    jsonschema.Draft202012Validator(
        _schema(), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(evenements[0].model_dump(mode="json"))


async def test_la_tache_ne_lit_pas_paiements_si_le_paiement_n_a_jamais_ete_demande(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(
        depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1), paiement_demande=False
    )

    await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert _statut(depot, commande) is StatutCommande.EXPIREE
    assert paiements_espion.lectures == []
    assert paiements_espion.paiements_postes == []


async def test_la_tache_signale_le_remboursement_du_quand_le_paiement_a_ete_accepte(
    depot: Any,
    horloge: Any,
    paiements_espion: PaiementsEspion,
    caplog: pytest.LogCaptureFixture,
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(
        depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1), paiement_demande=True
    )
    paiements_espion.statuts[commande.id] = "ACCEPTE"

    with caplog.at_level(logging.ERROR):
        await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert _statut(depot, commande) is StatutCommande.EXPIREE
    evenements = _expirations_de(depot, commande)
    assert len(evenements) == 1
    assert evenements[0].data.get("remboursement_du") is True
    erreurs = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any(str(commande.id) in message for message in erreurs), erreurs
    # Le journal ne porte que l'identifiant de la commande : ni client, ni e-mail.
    for message in erreurs:
        assert commande.client not in message
        assert "client.test@exemple.test" not in message


@pytest.mark.parametrize(
    "statut_lu", ["REFUSE", "REMBOURSE", None], ids=["refuse", "rembourse", "absent"]
)
async def test_la_tache_ne_signale_aucun_remboursement_pour_un_paiement_refuse_rembourse_ou_absent(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion, statut_lu: str | None
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(
        depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1), paiement_demande=True
    )
    if statut_lu is not None:
        paiements_espion.statuts[commande.id] = statut_lu

    await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert _statut(depot, commande) is StatutCommande.EXPIREE
    evenements = _expirations_de(depot, commande)
    assert len(evenements) == 1
    assert "remboursement_du" not in evenements[0].data


async def test_la_tache_ne_poste_jamais_de_paiement(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(
        depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1), paiement_demande=True
    )
    paiements_espion.statuts[commande.id] = "ACCEPTE"

    await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert paiements_espion.lectures == [commande.id]
    assert paiements_espion.paiements_postes == []


async def test_paiements_injoignable_laisse_la_commande_en_attente_sans_interrompre_le_cycle(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    premiere = _semer(
        depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=2), paiement_demande=True
    )
    seconde = _semer(depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1))
    paiements_espion.injoignable = True

    expirees = await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert expirees == 1
    assert _statut(depot, premiere) is StatutCommande.EN_ATTENTE
    assert _expirations_de(depot, premiere) == []
    assert _statut(depot, seconde) is StatutCommande.EXPIREE
    assert len(_expirations_de(depot, seconde)) == 1


async def test_une_commande_laissee_en_attente_est_expiree_au_cycle_suivant(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(
        depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1), paiement_demande=True
    )
    paiements_espion.injoignable = True
    await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)
    assert _statut(depot, commande) is StatutCommande.EN_ATTENTE

    # Cycle 2 : Paiements de nouveau joignable, aucun paiement (404).
    paiements_espion.injoignable = False
    await expirer_commandes_depassees(
        depot, paiements_espion, maintenant + timedelta(seconds=PERIODE), lot=LOT
    )

    assert _statut(depot, commande) is StatutCommande.EXPIREE
    assert len(_expirations_de(depot, commande)) == 1


async def test_la_tache_n_expire_pas_une_commande_dont_l_echeance_a_ete_repoussee_depuis_la_selection(  # noqa: E501 (nom du plan)
    depot: Any,
    horloge: Any,
    paiements_espion: PaiementsEspion,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maintenant = _maintenant(horloge)
    # Relue sous verrou : payerCommande vient de repousser l'échéance (H3).
    commande = _semer(depot, StatutCommande.EN_ATTENTE, maintenant + timedelta(hours=1))
    selectionnee = replace(commande, expire_le=maintenant - timedelta(seconds=1))

    async def selection_perimee(_maintenant: datetime, _limite: int) -> list[Commande]:
        return [selectionnee]

    monkeypatch.setattr(depot, "lister_a_expirer", selection_perimee)

    expirees = await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=LOT)

    assert expirees == 0
    assert _statut(depot, commande) is StatutCommande.EN_ATTENTE
    assert _expirations(depot) == []


async def test_la_tache_traite_au_plus_un_lot_par_cycle_par_echeance_croissante(
    depot: Any, horloge: Any, paiements_espion: PaiementsEspion
) -> None:
    maintenant = _maintenant(horloge)
    # Semées dans le désordre : la plus récente d'abord.
    recente = _semer(depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1))
    ancienne = _semer(depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=3))
    moyenne = _semer(depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=2))

    expirees = await expirer_commandes_depassees(depot, paiements_espion, maintenant, lot=2)

    assert expirees == 2
    assert _statut(depot, ancienne) is StatutCommande.EXPIREE
    assert _statut(depot, moyenne) is StatutCommande.EXPIREE
    assert _statut(depot, recente) is StatutCommande.EN_ATTENTE

    await expirer_commandes_depassees(
        depot, paiements_espion, maintenant + timedelta(seconds=PERIODE), lot=2
    )

    assert _statut(depot, recente) is StatutCommande.EXPIREE
    assert len(_expirations(depot)) == 3


# --- CA2 : verrou du cycle ----------------------------------------------------------------------


async def test_la_tache_ne_selectionne_rien_sans_le_verrou_du_cycle(
    depot: Any,
    horloge: Any,
    paiements_espion: PaiementsEspion,
    verrou: VerrouTacheEnMemoire,
    lectures_du_depot: list[tuple[datetime, int]],
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1))
    verrou.cles[CLE_VERROU_TACHE] = ("commandes-2", int(PERIODE * 1000))

    execute = await executer_cycle(
        verrou,
        depot,
        paiements_espion,
        maintenant,
        instance="commandes-1",
        periode=PERIODE,
        lot=LOT,
    )

    assert execute is False
    assert lectures_du_depot == []
    assert _statut(depot, commande) is StatutCommande.EN_ATTENTE
    assert _expirations(depot) == []
    assert verrou.cles[CLE_VERROU_TACHE] == ("commandes-2", int(PERIODE * 1000))


async def test_la_tache_s_execute_quand_elle_obtient_le_verrou_du_cycle(
    depot: Any,
    horloge: Any,
    paiements_espion: PaiementsEspion,
    verrou: VerrouTacheEnMemoire,
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1))

    execute = await executer_cycle(
        verrou,
        depot,
        paiements_espion,
        maintenant,
        instance="commandes-1",
        periode=PERIODE,
        lot=LOT,
    )

    assert execute is True
    # Valeur = instance, durée = une période ; jamais relâché en fin de cycle (Q1).
    assert verrou.cles == {CLE_VERROU_TACHE: ("commandes-1", 1000)}
    assert _statut(depot, commande) is StatutCommande.EXPIREE
    assert len(_expirations_de(depot, commande)) == 1


async def test_la_tache_saute_le_cycle_si_redis_est_injoignable(
    depot: Any,
    horloge: Any,
    paiements_espion: PaiementsEspion,
    verrou: VerrouTacheEnMemoire,
    lectures_du_depot: list[tuple[datetime, int]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    maintenant = _maintenant(horloge)
    commande = _semer(depot, StatutCommande.EN_ATTENTE, maintenant - timedelta(seconds=1))
    verrou.injoignable = True

    with caplog.at_level(logging.WARNING):
        execute = await executer_cycle(
            verrou,
            depot,
            paiements_espion,
            maintenant,
            instance="commandes-1",
            periode=PERIODE,
            lot=LOT,
        )

    assert execute is False
    assert lectures_du_depot == []
    assert _statut(depot, commande) is StatutCommande.EN_ATTENTE
    assert [r for r in caplog.records if r.levelno == logging.WARNING] != []


# --- Course paiement / expiration : reverrouillage d'une commande expirée (review BIL-010) --------


class BilletsQuiExpireLaCommande:
    """Double de `ClientBillets` : accorde chaque verrou ; au reverrouillage en confirmation, la
    commande passe EXPIREE dans le dépôt, comme si la tâche l'avait expirée pendant l'appel."""

    def __init__(self, depot: Any, horloge: Any) -> None:
        self.depot = depot
        self.horloge = horloge
        self.confirmations: list[UUID] = []

    async def verrouiller_place(
        self, place_id: UUID, *, seance_id: UUID, commande_id: UUID, confirmation: bool
    ) -> VerrouPlace:
        if confirmation:
            self.confirmations.append(place_id)
            commande = self.depot.commandes[commande_id]
            self.depot.commandes[commande_id] = replace(commande, statut=StatutCommande.EXPIREE)
        return VerrouPlace(
            place_id=place_id,
            seance_id=seance_id,
            categorie_id=uuid4(),
            commande_id=commande_id,
            expire_le=_maintenant(self.horloge) + timedelta(hours=1),
        )


async def test_un_paiement_dont_la_commande_expire_pendant_le_reverrouillage_republie_l_expiration(  # noqa: E501 (nom demandé)
    app: FastAPI,
    client: httpx.AsyncClient,
    depot: Any,
    horloge: Any,
    seance: Any,
    entetes_a: dict[str, str],
    paiements_espion: PaiementsEspion,
) -> None:
    places = [seance["A1"], seance["A2"], seance["C1"]]
    commande: Commande = depot.semer(
        "client-a",
        seance.id,
        StatutCommande.EN_ATTENTE,
        email="client.test@exemple.test",
        place_ids=places,
    )
    billets = BilletsQuiExpireLaCommande(depot, horloge)
    app.dependency_overrides[obtenir_billets] = lambda: billets
    app.dependency_overrides[obtenir_paiements] = lambda: paiements_espion
    avant = len(_expirations_de(depot, commande))

    reponse = await client.post(
        f"/api/v1/orders/{commande.id}/payment",
        json={"carte_test": "4242424242424242"},
        headers=entetes_a,
    )

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["code"] == "ORDER_NOT_PENDING"
    assert billets.confirmations == places
    assert paiements_espion.paiements_postes == []
    assert _statut(depot, commande) is StatutCommande.EXPIREE
    evenements = _expirations_de(depot, commande)
    assert len(evenements) == avant + 1
    republie = evenements[-1]
    assert republie.data == {
        "commande_id": str(commande.id),
        "seance_id": str(seance.id),
        "place_ids": [str(p) for p in places],
    }
    jsonschema.Draft202012Validator(
        _schema(), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(republie.model_dump(mode="json"))
