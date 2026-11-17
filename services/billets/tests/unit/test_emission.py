"""Émission des billets d'une commande confirmée (CA1 et E1 du plan BIL-009), sans base.

Fonctions de domaine `billets_a_emettre` et `rejet_de_commande` appelées directement, sur le
`data` de ticketing.order.confirmed de la commande `C1` du plan.
"""

import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from billets.domaine.emission import (
    STATUT_EMIS,
    DonneesCommandeInvalides,
    MotifRefus,
    billets_a_emettre,
    rejet_de_commande,
)

MAINTENANT = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


class CommandeC1:
    """Commande `C1` du plan : lignes A1 et A2 à 4500 centimes, séance `S`."""

    def __init__(self) -> None:
        self.id = uuid4()
        self.seance_id = uuid4()
        self.a1 = uuid4()
        self.a2 = uuid4()

    def data(self) -> dict[str, Any]:
        return {
            "commande_id": str(self.id),
            "client": "client-test",
            "email": "client.test@exemple.test",
            "seance_id": str(self.seance_id),
            "lignes": [
                {"place_id": str(self.a1), "montant": 4500},
                {"place_id": str(self.a2), "montant": 4500},
            ],
            "montant_total": 9000,
        }


@pytest.fixture
def c1() -> CommandeC1:
    return CommandeC1()


@pytest.fixture
def cle() -> str:
    return secrets.token_urlsafe(32)


# --- CA1 ----------------------------------------------------------------------------------------


def test_une_commande_confirmee_donne_un_billet_emis_par_ligne(c1: CommandeC1, cle: str) -> None:
    billets = billets_a_emettre(c1.data(), emis_le=MAINTENANT, cle=cle)

    assert len(billets) == 2
    assert {b.place_id for b in billets} == {c1.a1, c1.a2}
    assert len({b.id for b in billets}) == 2
    for billet in billets:
        assert billet.statut == STATUT_EMIS == "EMIS"
        assert billet.commande_id == c1.id
        assert billet.client == "client-test"
        assert billet.seance_id == c1.seance_id
        assert billet.emis_le == MAINTENANT
        assert billet.qr_code


def _sans_lignes(data: dict[str, Any]) -> None:
    data["lignes"] = []


def _place_non_uuid(data: dict[str, Any]) -> None:
    data["lignes"][0]["place_id"] = "pas-un-uuid"


def _sans_seance(data: dict[str, Any]) -> None:
    del data["seance_id"]


@pytest.mark.parametrize(
    "alterer",
    [_sans_lignes, _place_non_uuid, _sans_seance],
    ids=["lignes_vide", "place_id_non_uuid", "seance_id_absent"],
)
def test_un_order_confirmed_invalide_leve_une_erreur(
    c1: CommandeC1, cle: str, alterer: Any
) -> None:
    data = c1.data()
    alterer(data)
    billets: Any = None

    with pytest.raises(DonneesCommandeInvalides):
        billets = billets_a_emettre(data, emis_le=MAINTENANT, cle=cle)

    assert billets is None


# --- E1 : refus d'émission (Q1) -----------------------------------------------------------------


@pytest.mark.parametrize("cas", ["place_deja_vendue", "seance_annulee"])
def test_le_rejet_porte_les_places_en_conflit_ou_toutes_les_places_si_la_seance_est_annulee(
    c1: CommandeC1, cas: str
) -> None:
    attendu: tuple[MotifRefus, tuple[UUID, ...]]
    if cas == "place_deja_vendue":
        refus = rejet_de_commande(c1.data(), places_en_conflit={c1.a1}, seance_annulee=False)
        attendu = (MotifRefus.PLACE_DEJA_VENDUE, (c1.a1,))
    else:
        refus = rejet_de_commande(c1.data(), places_en_conflit=set(), seance_annulee=True)
        attendu = (MotifRefus.SEANCE_ANNULEE, (c1.a1, c1.a2))

    assert (refus.motif, tuple(refus.place_ids)) == attendu
    assert refus.commande_id == c1.id
    assert refus.seance_id == c1.seance_id
