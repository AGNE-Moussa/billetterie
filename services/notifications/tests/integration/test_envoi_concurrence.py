"""BIL-009, CA3 (décision Q7) : dix traitements simultanés du même ticketing.ticket.issued
n'envoient qu'un e-mail (plan docs/test-plans/BIL-009.md).

Chaque traitement tourne dans sa propre session et sa transaction, sur la vraie base du module,
avec le vrai `EnvoyeurSmtp` vers Mailpit ; seuls l'historique `envois`
(`uq_envois_evenement_commande`) et l'ordre « inscrire puis envoyer » empêchent le doublon.
Marqueur `concurrence` : joué par `make test-concurrence`.
"""

import asyncio
from typing import Any

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from notifications.consommateurs import traitement_billet_emis
from notifications.infra.smtp import EnvoyeurSmtp

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

LIVRAISONS = 10
DELAI_SMTP = 5.0


async def test_deux_livraisons_simultanees_du_meme_ticket_issued_ne_produisent_qu_un_e_mail(
    base: Any, sessions: async_sessionmaker[AsyncSession], boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    billet = c1.ticket_issued("A1")
    traitement = traitement_billet_emis(
        EnvoyeurSmtp(boite.smtp_hote, boite.smtp_port, DELAI_SMTP), outils.expediteur
    )

    erreurs = await asyncio.gather(
        *(outils.traiter(sessions, traitement, billet) for _ in range(LIVRAISONS))
    )

    await boite.attendre(1)
    await anyio.sleep(outils.attente_doublon)
    recus = await boite.messages()
    assert len(recus) == 1, f"{len(recus)} e-mails pour {LIVRAISONS} livraisons simultanées"
    envois = await base.envois()
    assert len(envois) == 1, envois
    assert [e for e in erreurs if e is not None] == []
