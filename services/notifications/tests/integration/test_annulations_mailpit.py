"""BIL-011, CA2 (Q7) : échec SMTP au milieu des e-mails d'annulation d'une séance, puis nouvel
essai du message (review docs/reviews/BIL-011.md, « À couvrir », point 8).

Livraisons par `commun.consommateurs.traiter_une_fois` (file `notifications.show-cancelled`) sur
la vraie base du module, envois par le vrai `EnvoyeurSmtp` vers Mailpit. La panne est réelle :
l'envoi de la deuxième commande part vers un port SMTP fermé (connexion refusée). Une
transaction par commande : les commandes déjà servies ne reçoivent rien de plus au nouvel essai.
"""

import logging
import socket
import uuid
from email.message import EmailMessage
from typing import Any

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commun.consommateurs import traiter_une_fois
from commun.evenements import Evenement
from notifications.consommateurs import traitement_seance_annulee
from notifications.infra.smtp import EnvoyeurSmtp

pytestmark = pytest.mark.anyio

CONSOMMATEUR = "notifications.show-cancelled"
DELAI_SMTP = 5.0
ADRESSES = ("client2.test@exemple.test", "client3.test@exemple.test")


def port_ferme() -> int:
    """Port local libre, sans serveur à l'écoute : toute connexion y est refusée."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prise:
        prise.bind(("127.0.0.1", 0))
        return int(prise.getsockname()[1])


class EnvoyeurEnPanneAuDeuxieme:
    """Vrai SMTP vers Mailpit, sauf le deuxième envoi, vers un port fermé."""

    def __init__(self, mailpit: EnvoyeurSmtp, ferme: EnvoyeurSmtp) -> None:
        self._mailpit = mailpit
        self._ferme = ferme
        self.envois = 0

    async def envoyer(self, message: EmailMessage) -> None:
        self.envois += 1
        envoyeur = self._ferme if self.envois == 2 else self._mailpit
        await envoyeur.envoyer(message)


async def test_un_echec_smtp_au_milieu_puis_un_nouvel_essai_n_envoie_qu_un_e_mail_par_commande(
    base: Any,
    sessions: async_sessionmaker[AsyncSession],
    boite: Any,
    outils: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    for adresse in ADRESSES:
        await base.inserer_destinataire(uuid.uuid4(), adresse, c1.seance_id)
    message = Evenement(
        type="ticketing.show.cancelled",
        correlation_id=outils.correlation,
        data={"seance_id": str(c1.seance_id), "evenement_id": str(uuid.uuid4())},
    )
    mailpit = EnvoyeurSmtp(boite.smtp_hote, boite.smtp_port, DELAI_SMTP)
    en_panne = EnvoyeurEnPanneAuDeuxieme(mailpit, EnvoyeurSmtp("127.0.0.1", port_ferme(), 2.0))

    with pytest.raises(OSError):
        await traiter_une_fois(
            sessions,
            CONSOMMATEUR,
            traitement_seance_annulee(sessions, en_panne, outils.expediteur),
            message,
        )
    apres_panne = await boite.attendre(1)
    envois_apres_panne = await base.envois()
    traites_apres_panne = await base.traites(CONSOMMATEUR, message.id)

    await traiter_une_fois(
        sessions,
        CONSOMMATEUR,
        traitement_seance_annulee(sessions, mailpit, outils.expediteur),
        message,
    )
    await boite.attendre(3)
    await anyio.sleep(outils.attente_doublon)

    assert len(apres_panne) == 1, apres_panne
    assert len(envois_apres_panne) == 1, envois_apres_panne
    assert traites_apres_panne == 0
    recus = await boite.messages()
    adresses = sorted(d["Address"] for m in recus for d in m["To"])
    assert adresses == sorted([outils.email_c1, *ADRESSES]), adresses
    assert len(await base.envois()) == 3
    assert await base.traites(CONSOMMATEUR, message.id) == 1
    for adresse in (outils.email_c1, *ADRESSES):
        assert adresse not in caplog.text, f"adresse {adresse} dans les journaux"
