"""BIL-009, CA1, CA3, E2, E3 : consommateurs de notifications sur un vrai RabbitMQ (plan
docs/test-plans/BIL-009.md).

Le service démarre avec `rabbitmq_url` (files `notifications.order-confirmed` et
`notifications.ticket-issued`, commun.consommateurs) et le SMTP de Mailpit ; les événements sont
publiés sur l'exchange `ticketing` dans l'enveloppe `commun.evenements.Evenement`.

Pannes SMTP (E3) : `docker pause` de Mailpit avec `SMTP_DELAI=1`, puis `unpause` ; panne franche :
port SMTP fermé.
"""

import socket
from typing import Any

import anyio
import pytest

pytestmark = pytest.mark.anyio

# Pause de Mailpit pendant la première livraison (SMTP_DELAI=1 : l'envoi dépasse le délai).
DELAI_SMTP_COURT = 1.0
PAUSE_MAILPIT = 1.2


def _port_ferme() -> int:
    """Port local libre, sans serveur à l'écoute : connexion refusée."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prise:
        prise.bind(("127.0.0.1", 0))
        return int(prise.getsockname()[1])


async def test_l_envoi_est_inscrit_dans_l_historique(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    billet = c1.ticket_issued("A1")

    async with service_notifications():
        await outils.publier(rabbitmq_url, billet)

        async def inscrit() -> bool:
            return len(await base.envois()) >= 1

        await outils.jusqua(inscrit)

    envois = await base.envois()
    assert len(envois) == 1, envois
    (envoi,) = envois
    assert envoi["evenement_id"] == billet.id
    assert envoi["type_evenement"] == outils.evenement_billet_emis
    assert envoi["commande_id"] == c1.commande_id
    assert envoi["destinataire"] == outils.email_c1
    assert envoi["envoye_le"].tzinfo is not None
    assert await base.traites(outils.consommateur_billet, billet.id) == 1


async def test_le_consommateur_de_notifications_recoit_ticket_issued_depuis_rabbitmq(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()

    async with service_notifications():
        await outils.publier(rabbitmq_url, c1.order_confirmed())

        async def destinataire_connu() -> bool:
            return len(await base.destinataires()) == 1

        await outils.jusqua(destinataire_connu)
        await outils.publier(rabbitmq_url, c1.ticket_issued("A1"))
        recus = await boite.attendre(1)

    assert len(recus) == 1, f"{len(recus)} e-mails dans Mailpit au lieu de 1"
    assert [d["Address"] for d in recus[0]["To"]] == [outils.email_c1]


@pytest.mark.parametrize("identifiant", ["meme_id", "autre_id"])
async def test_order_confirmed_rejoue_ne_cree_qu_un_destinataire(
    identifiant: str,
    service_notifications: Any,
    rabbitmq_url: str,
    base: Any,
    boite: Any,
    outils: Any,
) -> None:
    c1 = outils.commande_c1()
    premier = c1.order_confirmed()
    second = premier if identifiant == "meme_id" else c1.order_confirmed()
    attendus = 1 if identifiant == "meme_id" else 2

    async with service_notifications():
        await outils.publier(rabbitmq_url, premier, second)

        async def traites() -> bool:
            return await base.traites(outils.consommateur_commande) == attendus

        await outils.jusqua(traites)
        await anyio.sleep(outils.attente_doublon)

    destinataires = await base.destinataires()
    assert len(destinataires) == 1, destinataires
    assert await base.traites(outils.consommateur_commande) == attendus
    en_erreur = await outils.lire_file_erreur(rabbitmq_url, outils.consommateur_commande)
    assert not ({str(premier.id), str(second.id)} & set(en_erreur)), en_erreur


async def test_ticket_issued_rejoue_ne_produit_qu_un_e_mail(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    billet = c1.ticket_issued("A1")

    async with service_notifications():
        await outils.publier(rabbitmq_url, billet, billet)
        await boite.attendre(1)
        await anyio.sleep(outils.attente_doublon)

    recus = await boite.messages()
    assert len(recus) == 1, f"{len(recus)} e-mails pour un message livré deux fois"
    assert len(await base.envois()) == 1


async def test_ticket_issued_d_une_commande_jamais_confirmee_finit_en_dlq_sans_e_mail(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    billet = c1.ticket_issued("A1")
    en_erreur: list[str] = []

    async with service_notifications():
        await outils.publier(rabbitmq_url, billet)

        async def en_dlq() -> bool:
            en_erreur.extend(
                await outils.lire_file_erreur(rabbitmq_url, outils.consommateur_billet)
            )
            return str(billet.id) in en_erreur

        await outils.jusqua(en_dlq)

    assert str(billet.id) in en_erreur, f"message absent de la DLQ : {en_erreur}"
    assert await boite.messages() == []
    assert await base.envois() == []


async def test_une_commande_de_revendeur_n_envoie_rien_et_n_inscrit_aucun_envoi(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    revendeur = outils.commande_revendeur()
    billet = revendeur.ticket_issued("A3")

    async with service_notifications():
        await outils.publier(rabbitmq_url, revendeur.order_confirmed())

        async def destinataire_connu() -> bool:
            return len(await base.destinataires()) == 1

        await outils.jusqua(destinataire_connu)
        await outils.publier(rabbitmq_url, billet)

        async def traite() -> bool:
            return await base.traites(outils.consommateur_billet, billet.id) == 1

        await outils.jusqua(traite)
        await anyio.sleep(outils.attente_doublon)

    assert await base.traites(outils.consommateur_billet, billet.id) == 1
    assert await boite.messages() == []
    assert await base.envois() == []


async def test_smtp_injoignable_puis_revenu_envoie_un_seul_e_mail(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    billet = c1.ticket_issued("A1")
    conteneur = boite.conteneur.get_wrapped_container()

    async with service_notifications(smtp_delai=DELAI_SMTP_COURT):
        conteneur.pause()
        try:
            await outils.publier(rabbitmq_url, billet)
            await anyio.sleep(PAUSE_MAILPIT)
        finally:
            conteneur.unpause()
        await boite.attendre(1)
        await anyio.sleep(outils.attente_doublon)

    recus = await boite.messages()
    assert len(recus) == 1, f"{len(recus)} e-mails après le retour du SMTP au lieu de 1"
    assert len(await base.envois()) == 1
    en_erreur = await outils.lire_file_erreur(rabbitmq_url, outils.consommateur_billet)
    assert str(billet.id) not in en_erreur


async def test_smtp_toujours_injoignable_envoie_le_message_en_dlq_sans_envoi_inscrit(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    billet = c1.ticket_issued("A1")
    en_erreur: list[str] = []

    async with service_notifications(smtp_hote="127.0.0.1", smtp_port=_port_ferme()):
        await outils.publier(rabbitmq_url, billet)

        async def en_dlq() -> bool:
            en_erreur.extend(
                await outils.lire_file_erreur(rabbitmq_url, outils.consommateur_billet)
            )
            return str(billet.id) in en_erreur

        await outils.jusqua(en_dlq)

    assert str(billet.id) in en_erreur, f"message absent de la DLQ : {en_erreur}"
    assert await base.envois() == []
    assert await base.traites(outils.consommateur_billet, billet.id) == 0
