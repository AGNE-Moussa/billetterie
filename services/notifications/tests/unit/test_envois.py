"""Envoi des billets par e-mail (CA1, CA3, E2, E3 du plan BIL-009), sans base ni SMTP.

`envoyer_billet` est appelé dans la transaction simulée du dépôt en mémoire, avec un envoyeur en
mémoire. Données du plan : commande `C1` (`client.test@exemple.test`), commande revendeur `R`
(`email` null).
"""

import smtplib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from commun.evenements import Evenement
from notifications.config import EXPEDITEUR_PAR_DEFAUT
from notifications.domaine.envois import (
    EVENEMENT_BILLET_EMIS,
    CommandeInconnue,
    Destinataire,
    DonneesInvalides,
    envoyer_billet,
)

pytestmark = pytest.mark.anyio

MAINTENANT = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
EMAIL_C1 = "client.test@exemple.test"
CORRELATION = "correlation-bil-009-1"


def _ticket_issued(commande_id: UUID, seance_id: UUID) -> Evenement:
    """ticketing.ticket.issued d'un billet de la commande (place A1 ou A3 du plan)."""
    billet_id = uuid4()
    data = {
        "billet_id": str(billet_id),
        "commande_id": str(commande_id),
        "seance_id": str(seance_id),
        "place_id": str(uuid4()),
        "qr_code": f"{billet_id}.signature-de-test",
        "emis_le": MAINTENANT.isoformat(),
    }
    return Evenement(type=EVENEMENT_BILLET_EMIS, data=data, correlation_id=CORRELATION)


async def _traiter(depot: Any, envoyeur: Any, evenement: Evenement) -> None:
    async with depot.transaction():
        await envoyer_billet(
            depot,
            envoyeur,
            evenement,
            expediteur=EXPEDITEUR_PAR_DEFAUT,
            maintenant=MAINTENANT,
        )


def _destinataire_c1(depot: Any, email: str | None = EMAIL_C1) -> Destinataire:
    destinataire = Destinataire(commande_id=uuid4(), email=email, seance_id=uuid4())
    depot.semer_destinataire(destinataire)
    return destinataire


# --- CA1 ----------------------------------------------------------------------------------------


async def test_un_billet_avec_destinataire_produit_un_message_pour_lui(
    depot: Any, envoyeur: Any
) -> None:
    c1 = _destinataire_c1(depot)
    evenement = _ticket_issued(c1.commande_id, c1.seance_id)

    await _traiter(depot, envoyeur, evenement)

    assert len(envoyeur.messages) == 1
    message = envoyeur.messages[0]
    assert message["To"] == EMAIL_C1
    assert message["From"] == "billetterie@exemple.test"
    pieces = list(message.iter_attachments())
    assert len(pieces) == 1
    assert pieces[0].get_content_type() == "image/png"
    assert pieces[0].get_content()
    corps = message.get_body(preferencelist=("plain",))
    assert corps is not None
    assert evenement.data["qr_code"] in corps.get_content()


def _billet_non_uuid(data: dict[str, Any]) -> None:
    data["billet_id"] = "pas-un-uuid"


def _qr_vide(data: dict[str, Any]) -> None:
    data["qr_code"] = ""


def _sans_commande(data: dict[str, Any]) -> None:
    del data["commande_id"]


@pytest.mark.parametrize(
    "alterer",
    [_billet_non_uuid, _qr_vide, _sans_commande],
    ids=["billet_id_non_uuid", "qr_code_vide", "commande_id_absent"],
)
async def test_un_ticket_issued_invalide_leve_une_erreur(
    depot: Any, envoyeur: Any, alterer: Any
) -> None:
    c1 = _destinataire_c1(depot)
    evenement = _ticket_issued(c1.commande_id, c1.seance_id)
    alterer(evenement.data)

    with pytest.raises(DonneesInvalides):
        await _traiter(depot, envoyeur, evenement)

    assert envoyeur.appels == 0
    assert depot.envois == []


# --- CA3 ----------------------------------------------------------------------------------------


async def test_un_ticket_issued_deja_envoye_n_est_pas_renvoye(depot: Any, envoyeur: Any) -> None:
    c1 = _destinataire_c1(depot)
    evenement = _ticket_issued(c1.commande_id, c1.seance_id)

    await _traiter(depot, envoyeur, evenement)
    await _traiter(depot, envoyeur, evenement)

    assert len(envoyeur.messages) == 1
    assert len(depot.envois) == 1
    envoi = depot.envois[0]
    assert envoi.evenement_id == evenement.id
    assert envoi.commande_id == c1.commande_id
    assert envoi.destinataire == EMAIL_C1


# --- E2 : destinataires de commande -------------------------------------------------------------


async def test_un_ticket_issued_d_une_commande_inconnue_leve_une_erreur(
    depot: Any, envoyeur: Any
) -> None:
    evenement = _ticket_issued(uuid4(), uuid4())

    with pytest.raises(CommandeInconnue):
        await _traiter(depot, envoyeur, evenement)

    assert envoyeur.appels == 0
    assert depot.envois == []


async def test_un_destinataire_sans_email_n_envoie_rien(depot: Any, envoyeur: Any) -> None:
    revendeur = _destinataire_c1(depot, email=None)
    evenement = _ticket_issued(revendeur.commande_id, revendeur.seance_id)

    await _traiter(depot, envoyeur, evenement)

    assert envoyeur.appels == 0
    assert depot.envois == []


# --- E3 : SMTP injoignable (Q7) -----------------------------------------------------------------


@pytest.mark.parametrize(
    "erreur",
    [OSError("SMTP injoignable"), smtplib.SMTPException("SMTP en échec")],
    ids=["OSError", "SMTPException"],
)
async def test_un_echec_smtp_leve_une_erreur_sans_inscrire_d_envoi(
    depot: Any, envoyeur: Any, erreur: Exception
) -> None:
    c1 = _destinataire_c1(depot)
    evenement = _ticket_issued(c1.commande_id, c1.seance_id)
    envoyeur.erreur = erreur

    with pytest.raises(type(erreur)):
        await _traiter(depot, envoyeur, evenement)

    assert envoyeur.appels == 1
    assert depot.envois == []
