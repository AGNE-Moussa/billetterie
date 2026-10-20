"""Enveloppe des événements (commun.evenements)."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from commun.correlation import correlation
from commun.evenements import Evenement


def test_l_enveloppe_contient_les_champs_de_la_convention() -> None:
    evenement = Evenement.creer("ticketing.order.confirmed", {"commande_id": "42"})

    assert isinstance(evenement.id, uuid.UUID)
    assert evenement.version == 1
    assert evenement.occurred_at.tzinfo is UTC
    assert evenement.occurred_at <= datetime.now(UTC)
    assert set(evenement.model_dump()) == {
        "id",
        "type",
        "version",
        "occurred_at",
        "correlation_id",
        "data",
    }


def test_l_evenement_reprend_la_correlation_de_la_requete() -> None:
    with correlation("requete-12"):
        evenement = Evenement.creer("ticketing.ticket.issued", {})

    assert evenement.correlation_id == "requete-12"


@pytest.mark.parametrize(
    "type_evenement",
    ["order.confirmed", "ticketing.order", "ticketing.Order.confirmed", "autre.order.confirmed"],
)
def test_un_type_hors_convention_est_refuse(type_evenement: str) -> None:
    with pytest.raises(ValidationError):
        Evenement.creer(type_evenement, {})


def test_l_enveloppe_survit_a_un_aller_retour_json() -> None:
    evenement = Evenement.creer("ticketing.show.cancelled", {"seance_id": "7"}, version=2)

    assert Evenement.model_validate_json(evenement.model_dump_json()) == evenement
