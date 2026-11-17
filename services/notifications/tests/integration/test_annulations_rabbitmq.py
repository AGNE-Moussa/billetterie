"""BIL-011, CA2 (Q6, Q7, H7) : e-mails d'annulation et de remboursement, service démarré avec
ses consommateurs sur un vrai RabbitMQ et le SMTP de Mailpit (plan docs/test-plans/BIL-011.md).

Files `notifications.show-cancelled` et `notifications.payment-refunded` ; événements publiés
sur l'exchange `ticketing` dans l'enveloppe `commun.evenements.Evenement`. Destinataires
synthétiques déjà enregistrés en base (`destinataires_commande`) : `C1`
(`client.test@exemple.test`) et `C5` (`client2.test@exemple.test`) sur la séance `S`.
"""

import uuid
from typing import Any

import anyio
import pytest

from commun.evenements import Evenement

pytestmark = pytest.mark.anyio

EMAIL_C5 = "client2.test@exemple.test"
SEANCE_ANNULEE = "ticketing.show.cancelled"
PAIEMENT_REMBOURSE = "ticketing.payment.refunded"
CONSOMMATEUR_SEANCE = "notifications.show-cancelled"
CONSOMMATEUR_REMBOURSEMENT = "notifications.payment-refunded"
CORRELATION = "correlation-bil-011-1"


def show_cancelled(seance_id: uuid.UUID) -> Evenement:
    return Evenement(
        type=SEANCE_ANNULEE,
        correlation_id=CORRELATION,
        data={"seance_id": str(seance_id), "evenement_id": str(uuid.uuid4())},
    )


def payment_refunded(
    commande_id: uuid.UUID, seance_id: uuid.UUID, montant: int = 9000
) -> Evenement:
    return Evenement(
        type=PAIEMENT_REMBOURSE,
        correlation_id=CORRELATION,
        data={
            "paiement_id": str(uuid.uuid4()),
            "commande_id": str(commande_id),
            "seance_id": str(seance_id),
            "montant": montant,
        },
    )


async def deux_destinataires(base: Any, outils: Any) -> tuple[Any, uuid.UUID]:
    """C1 et C5 sur la même séance S ; renvoie (C1, identifiant de C5)."""
    c1 = outils.commande_c1()
    c5 = uuid.uuid4()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    await base.inserer_destinataire(c5, EMAIL_C5, c1.seance_id)
    return c1, c5


async def adresses(recus: list[dict[str, Any]]) -> list[str]:
    return sorted(d["Address"] for message in recus for d in message["To"])


async def envois_de(base: Any, type_evenement: str) -> list[Any]:
    return [e for e in await base.envois() if e["type_evenement"] == type_evenement]


async def test_un_e_mail_d_annulation_par_commande_arrive_dans_mailpit(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1, c5 = await deux_destinataires(base, outils)
    message = show_cancelled(c1.seance_id)

    async with service_notifications():
        await outils.publier(rabbitmq_url, message)
        await boite.attendre(2)
        await anyio.sleep(outils.attente_doublon)

    recus = await boite.messages()
    assert await adresses(recus) == sorted([outils.email_c1, EMAIL_C5]), recus
    sujets = {m["Subject"] for m in recus}
    assert len(sujets) == 1 and "" not in sujets, sujets
    for recu in recus:
        assert str(c1.seance_id) in (await boite.message(recu["ID"]))["Text"]
    envois = await envois_de(base, SEANCE_ANNULEE)
    assert sorted(e["commande_id"] for e in envois) == sorted([c1.commande_id, c5])
    assert all(e["evenement_id"] == message.id for e in envois)


async def test_show_cancelled_recu_deux_fois_n_envoie_qu_un_e_mail_par_commande(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1, _c5 = await deux_destinataires(base, outils)
    message = show_cancelled(c1.seance_id)

    async with service_notifications():
        await outils.publier(rabbitmq_url, message, message)
        await boite.attendre(2)
        await anyio.sleep(outils.attente_doublon)

    recus = await boite.messages()
    assert await adresses(recus) == sorted([outils.email_c1, EMAIL_C5]), recus
    assert len(await envois_de(base, SEANCE_ANNULEE)) == 2


async def test_une_seance_sans_destinataire_connu_n_envoie_rien(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    message = show_cancelled(uuid.uuid4())

    async with service_notifications():
        await outils.publier(rabbitmq_url, message)

        async def traite() -> bool:
            return await base.traites(CONSOMMATEUR_SEANCE, message.id) == 1

        await outils.jusqua(traite)
        await anyio.sleep(outils.attente_doublon)

    assert await base.traites(CONSOMMATEUR_SEANCE, message.id) == 1
    assert await boite.messages() == []
    assert await base.envois() == []
    en_erreur = await outils.lire_file_erreur(rabbitmq_url, CONSOMMATEUR_SEANCE)
    assert str(message.id) not in en_erreur


async def test_payment_refunded_envoie_l_e_mail_de_remboursement_a_l_acheteur(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    message = payment_refunded(c1.commande_id, c1.seance_id)

    async with service_notifications():
        await outils.publier(rabbitmq_url, message)
        await boite.attendre(1)
        await anyio.sleep(outils.attente_doublon)

    recus = await boite.messages()
    assert await adresses(recus) == [outils.email_c1], recus
    assert "90,00" in (await boite.message(recus[0]["ID"]))["Text"]
    envois = await envois_de(base, PAIEMENT_REMBOURSE)
    assert [(e["evenement_id"], e["commande_id"]) for e in envois] == [(message.id, c1.commande_id)]


async def test_payment_refunded_recu_deux_fois_n_envoie_qu_un_e_mail(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    message = payment_refunded(c1.commande_id, c1.seance_id)

    async with service_notifications():
        await outils.publier(rabbitmq_url, message, message)
        await boite.attendre(1)
        await anyio.sleep(outils.attente_doublon)

    assert len(await boite.messages()) == 1
    assert len(await envois_de(base, PAIEMENT_REMBOURSE)) == 1


async def test_payment_refunded_traite_apres_l_arrivee_du_destinataire_envoie_l_e_mail(
    service_notifications: Any, rabbitmq_url: str, base: Any, boite: Any, outils: Any
) -> None:
    c1 = outils.commande_c1()
    message = payment_refunded(c1.commande_id, c1.seance_id)

    async with service_notifications():
        # payment.refunded d'abord (destinataire inconnu : nouvel essai), puis order.confirmed.
        await outils.publier(rabbitmq_url, message, c1.order_confirmed())
        await boite.attendre(1)
        await anyio.sleep(outils.attente_doublon)

    recus = await boite.messages()
    assert await adresses(recus) == [outils.email_c1], recus
    en_erreur = await outils.lire_file_erreur(rabbitmq_url, CONSOMMATEUR_REMBOURSEMENT)
    assert str(message.id) not in en_erreur


@pytest.mark.parametrize("ordre", ["annulation_d_abord", "remboursement_d_abord"])
async def test_les_e_mails_d_annulation_et_de_remboursement_arrivent_dans_un_ordre_quelconque(
    ordre: str,
    service_notifications: Any,
    rabbitmq_url: str,
    base: Any,
    boite: Any,
    outils: Any,
) -> None:
    c1 = outils.commande_c1()
    await base.inserer_destinataire(c1.commande_id, outils.email_c1, c1.seance_id)
    messages = [show_cancelled(c1.seance_id), payment_refunded(c1.commande_id, c1.seance_id)]
    if ordre == "remboursement_d_abord":
        messages.reverse()

    async with service_notifications():
        await outils.publier(rabbitmq_url, *messages)
        await boite.attendre(2)
        await anyio.sleep(outils.attente_doublon)

    recus = await boite.messages()
    assert await adresses(recus) == [outils.email_c1, outils.email_c1], recus
    assert len({m["Subject"] for m in recus}) == 2, [m["Subject"] for m in recus]
    textes = [(await boite.message(m["ID"]))["Text"] for m in recus]
    assert sum("90,00" in texte for texte in textes) == 1, textes
    assert sorted(e["type_evenement"] for e in await base.envois()) == sorted(
        [SEANCE_ANNULEE, PAIEMENT_REMBOURSE]
    )
