"""BIL-011, CA2 (Q7) : livraisons simultanées du même ticketing.show.cancelled (plan
docs/test-plans/BIL-011.md).

Chaque traitement (`traitement_seance_annulee`) tourne dans sa propre session et sa transaction,
sur la vraie base du module, avec le vrai `EnvoyeurSmtp` vers Mailpit ; seuls l'historique
`envois` (`uq_envois_evenement_commande`) et l'ordre « inscrire puis envoyer » empêchent le
doublon. Marqueur `concurrence` : joué par `make test-concurrence`.
"""

import asyncio
import uuid
from typing import Any

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commun.evenements import Evenement
from notifications.consommateurs import traitement_seance_annulee
from notifications.infra.smtp import EnvoyeurSmtp

pytestmark = [pytest.mark.anyio, pytest.mark.concurrence]

DELAI_SMTP = 5.0
EMAIL_C5 = "client2.test@exemple.test"


@pytest.mark.parametrize("livraisons", [2, 10])
async def test_deux_livraisons_simultanees_de_show_cancelled_n_envoient_qu_un_e_mail_par_commande(  # noqa: E501 : nom du plan
    livraisons: int,
    base: Any,
    sessions: async_sessionmaker[AsyncSession],
    boite: Any,
    outils: Any,
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    await base.inserer_destinataire(uuid.uuid4(), EMAIL_C5, c1.seance_id)
    message = Evenement(
        type="ticketing.show.cancelled",
        correlation_id=outils.correlation,
        data={"seance_id": str(c1.seance_id), "evenement_id": str(uuid.uuid4())},
    )
    traitement = traitement_seance_annulee(
        sessions, EnvoyeurSmtp(boite.smtp_hote, boite.smtp_port, DELAI_SMTP), outils.expediteur
    )

    erreurs = await asyncio.gather(
        *(outils.traiter(sessions, traitement, message) for _ in range(livraisons))
    )

    await boite.attendre(2)
    await anyio.sleep(outils.attente_doublon)
    recus = await boite.messages()
    adresses = sorted(d["Address"] for m in recus for d in m["To"])
    assert adresses == sorted([outils.email_c1, EMAIL_C5]), (
        f"{len(recus)} e-mails pour {livraisons} livraisons simultanées : {adresses}"
    )
    assert len(await base.envois()) == 2
    assert [e for e in erreurs if e is not None] == []
