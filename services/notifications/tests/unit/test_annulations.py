"""E-mails d'annulation et de remboursement (CA2 du plan BIL-011), sans base ni SMTP.

`envoyer_annulation` et `envoyer_remboursement` (domaine.annulations) appelées directement avec
`DepotEnMemoire` et `EnvoyeurEnMemoire`. Destinataires du plan : `C1`
(client.test@exemple.test), `C5` (client2.test@exemple.test), `C3` (revendeur, `email` NULL)
sur `S`, `C4` sur `S2`.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any
from uuid import UUID, uuid4

import pytest

from commun.evenements import Evenement
from notifications.domaine.annulations import (
    EVENEMENT_PAIEMENT_REMBOURSE,
    EVENEMENT_SEANCE_ANNULEE,
    envoyer_annulation,
    envoyer_remboursement,
)
from notifications.domaine.envois import CommandeInconnue, Destinataire

pytestmark = pytest.mark.anyio

MAINTENANT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
EXPEDITEUR = "billetterie@exemple.test"
EMAIL_C1 = "client.test@exemple.test"
EMAIL_C5 = "client2.test@exemple.test"


@dataclass(frozen=True)
class Donnees:
    s: UUID
    s2: UUID
    c1: Destinataire
    c5: Destinataire
    c3: Destinataire
    c4: Destinataire


@pytest.fixture
def donnees(depot: Any) -> Donnees:
    s, s2 = uuid4(), uuid4()
    jeu = Donnees(
        s=s,
        s2=s2,
        c1=Destinataire(commande_id=uuid4(), email=EMAIL_C1, seance_id=s),
        c5=Destinataire(commande_id=uuid4(), email=EMAIL_C5, seance_id=s),
        c3=Destinataire(commande_id=uuid4(), email=None, seance_id=s),
        c4=Destinataire(commande_id=uuid4(), email="client4.test@exemple.test", seance_id=s2),
    )
    for destinataire in (jeu.c1, jeu.c5, jeu.c3, jeu.c4):
        depot.semer_destinataire(destinataire)
    return jeu


def _show_cancelled(seance_id: UUID) -> Evenement:
    return Evenement(
        type=EVENEMENT_SEANCE_ANNULEE,
        data={"seance_id": str(seance_id), "evenement_id": str(uuid4())},
    )


def _payment_refunded(destinataire: Destinataire, montant: int) -> Evenement:
    return Evenement(
        type=EVENEMENT_PAIEMENT_REMBOURSE,
        data={
            "paiement_id": str(uuid4()),
            "commande_id": str(destinataire.commande_id),
            "seance_id": str(destinataire.seance_id),
            "montant": montant,
        },
    )


def _texte(message: EmailMessage) -> str:
    corps = message.get_body(preferencelist=("plain",))
    assert corps is not None
    return str(corps.get_content())


async def _annuler(depot: Any, envoyeur: Any, evenement: Evenement) -> None:
    await envoyer_annulation(
        depot, envoyeur, evenement, expediteur=EXPEDITEUR, maintenant=MAINTENANT
    )


async def _rembourser(depot: Any, envoyeur: Any, evenement: Evenement) -> None:
    await envoyer_remboursement(
        depot, envoyeur, evenement, expediteur=EXPEDITEUR, maintenant=MAINTENANT
    )


async def test_show_cancelled_ecrit_a_chaque_destinataire_de_la_seance(
    depot: Any, envoyeur: Any, donnees: Donnees
) -> None:
    evenement = _show_cancelled(donnees.s)

    await _annuler(depot, envoyeur, evenement)

    assert sorted(m["To"] for m in envoyeur.messages) == sorted([EMAIL_C1, EMAIL_C5])
    for message in envoyeur.messages:
        assert message["From"] == EXPEDITEUR
        assert str(donnees.s) in _texte(message)
    assert {(e.commande_id, e.destinataire) for e in depot.envois} == {
        (donnees.c1.commande_id, EMAIL_C1),
        (donnees.c5.commande_id, EMAIL_C5),
    }
    for envoi in depot.envois:
        assert envoi.evenement_id == evenement.id
        assert envoi.type_evenement == EVENEMENT_SEANCE_ANNULEE
        assert envoi.envoye_le == MAINTENANT


@pytest.mark.parametrize("evenement_recu", ["show_cancelled", "payment_refunded"])
async def test_un_revendeur_sans_e_mail_ne_recoit_ni_annulation_ni_remboursement(
    depot: Any,
    envoyeur: Any,
    caplog: pytest.LogCaptureFixture,
    evenement_recu: str,
) -> None:
    caplog.set_level(logging.INFO)
    s = uuid4()
    c3 = Destinataire(commande_id=uuid4(), email=None, seance_id=s)
    depot.semer_destinataire(c3)

    if evenement_recu == "show_cancelled":
        await _annuler(depot, envoyeur, _show_cancelled(s))
    else:
        await _rembourser(depot, envoyeur, _payment_refunded(c3, 4500))

    assert envoyeur.messages == []
    assert envoyeur.appels == 0
    assert depot.envois == []
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(str(c3.commande_id) in r.getMessage() for r in infos), caplog.text
    assert "@" not in caplog.text


async def test_payment_refunded_avant_order_confirmed_est_reessaye(
    depot: Any, envoyeur: Any
) -> None:
    c1 = Destinataire(commande_id=uuid4(), email=EMAIL_C1, seance_id=uuid4())

    with pytest.raises(CommandeInconnue) as erreur:
        await _rembourser(depot, envoyeur, _payment_refunded(c1, 9000))

    assert erreur.value.commande_id == c1.commande_id
    assert envoyeur.messages == []
    assert depot.envois == []


async def test_les_journaux_ne_contiennent_aucune_adresse(
    depot: Any, envoyeur: Any, donnees: Donnees, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    await _annuler(depot, envoyeur, _show_cancelled(donnees.s))
    await _rembourser(depot, envoyeur, _payment_refunded(donnees.c1, 9000))
    await _rembourser(depot, envoyeur, _payment_refunded(donnees.c3, 4500))

    # Les traitements ont bien eu lieu (deux annulations, un remboursement) ...
    assert len(envoyeur.messages) == 3
    # ... sans qu'aucune adresse ni aucun jeton n'apparaisse dans les journaux.
    for adresse in (EMAIL_C1, EMAIL_C5, EXPEDITEUR):
        assert adresse not in caplog.text
    assert "@" not in caplog.text
    assert "Bearer" not in caplog.text
