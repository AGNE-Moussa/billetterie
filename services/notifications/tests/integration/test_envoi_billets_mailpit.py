"""BIL-009, CA1, CA3, E2 : traitements de notifications appelés directement, vraie base et vrai
Mailpit (plan docs/test-plans/BIL-009.md).

Chaque traitement (`enregistrer_destinataire_de_commande`, `traitement_billet_emis`) tourne dans
sa propre session et sa transaction, sur la base migrée du module ; l'envoi passe par le vrai
`EnvoyeurSmtp` vers Mailpit. La livraison par RabbitMQ (idempotence `messages_traites`, DLQ)
est couverte par test_consommateurs_rabbitmq.py.
"""

from typing import Any

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from notifications.consommateurs import (
    enregistrer_destinataire_de_commande,
    traitement_billet_emis,
)
from notifications.domaine.envois import CommandeInconnue
from notifications.infra.smtp import EnvoyeurSmtp

pytestmark = pytest.mark.anyio

SIGNATURE_PNG = b"\x89PNG\r\n\x1a\n"
DELAI_SMTP = 5.0


def _envoi(boite: Any, outils: Any) -> Any:
    """Traitement de ticketing.ticket.issued, branché sur le SMTP de Mailpit."""
    return traitement_billet_emis(
        EnvoyeurSmtp(boite.smtp_hote, boite.smtp_port, DELAI_SMTP), outils.expediteur
    )


async def test_notifications_enregistre_le_destinataire_de_chaque_commande_confirmee(
    base: Any, sessions: async_sessionmaker[AsyncSession], outils: Any
) -> None:
    c1, revendeur = outils.commande_c1(), outils.commande_revendeur()

    erreurs = [
        await outils.traiter(sessions, enregistrer_destinataire_de_commande, c1.order_confirmed()),
        await outils.traiter(
            sessions, enregistrer_destinataire_de_commande, revendeur.order_confirmed()
        ),
    ]

    lignes = {ligne["commande_id"]: ligne for ligne in await base.destinataires()}
    assert set(lignes) == {c1.commande_id, revendeur.commande_id}, lignes
    assert lignes[c1.commande_id]["email"] == outils.email_c1
    assert lignes[c1.commande_id]["seance_id"] == c1.seance_id
    assert lignes[revendeur.commande_id]["email"] is None
    assert erreurs == [None, None]


async def test_ticket_issued_envoie_un_e_mail_visible_dans_mailpit(
    base: Any, sessions: async_sessionmaker[AsyncSession], boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    billet = c1.ticket_issued("A1")

    erreur = await outils.traiter(sessions, _envoi(boite, outils), billet)

    recus = await boite.attendre(1)
    assert len(recus) == 1, f"{len(recus)} e-mails dans Mailpit au lieu de 1"
    (resume,) = recus
    assert [d["Address"] for d in resume["To"]] == [outils.email_c1]
    assert resume["From"]["Address"] == outils.expediteur
    detail = await boite.message(resume["ID"])
    assert billet.data["qr_code"] in detail["Text"], detail["Text"]
    images = await boite.images_png(resume["ID"])
    assert len(images) == 1, f"{len(images)} pièces jointes image/png"
    assert images[0].startswith(SIGNATURE_PNG)
    assert erreur is None


async def test_deux_billets_de_la_meme_commande_produisent_deux_e_mails(
    base: Any, sessions: async_sessionmaker[AsyncSession], boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    billets = [c1.ticket_issued("A1"), c1.ticket_issued("A2")]

    erreurs = [await outils.traiter(sessions, _envoi(boite, outils), b) for b in billets]

    recus = await boite.attendre(2)
    await anyio.sleep(outils.attente_doublon)
    assert len(await boite.messages()) == 2, f"{len(recus)} e-mails dans Mailpit au lieu de 2"
    envois = await base.envois()
    assert len(envois) == 2, envois
    assert {e["commande_id"] for e in envois} == {c1.commande_id}
    assert {e["evenement_id"] for e in envois} == {b.id for b in billets}
    assert erreurs == [None, None]


async def test_ticket_issued_avant_order_confirmed_echoue_puis_envoie_un_seul_e_mail(
    base: Any, sessions: async_sessionmaker[AsyncSession], boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    billet = c1.ticket_issued("A1")

    premier = await outils.traiter(sessions, _envoi(boite, outils), billet)

    assert isinstance(premier, CommandeInconnue), (
        f"premier traitement : {premier!r} au lieu de CommandeInconnue"
    )
    assert await base.envois() == []
    assert await boite.messages() == []

    erreur_commande = await outils.traiter(
        sessions, enregistrer_destinataire_de_commande, c1.order_confirmed()
    )
    rejeu = await outils.traiter(sessions, _envoi(boite, outils), billet)

    await boite.attendre(1)
    await anyio.sleep(outils.attente_doublon)
    recus = await boite.messages()
    assert len(recus) == 1, f"{len(recus)} e-mails après le rejeu au lieu de 1"
    assert len(await base.envois()) == 1
    assert (erreur_commande, rejeu) == (None, None)
