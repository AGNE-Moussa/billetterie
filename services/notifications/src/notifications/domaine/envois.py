"""Envoi des billets par e-mail : règles métier, sans SQLAlchemy ni SMTP.

- `ticketing.order.confirmed` tient `destinataires_commande` (docs/modele-donnees.md) : `email`
  NULL (revendeur) = rien à envoyer ; une commande absente = « pas encore reçue » (exception,
  nouvel essai).
- `ticketing.ticket.issued` : un e-mail par billet, QR joint en PNG et contenu du QR dans le
  corps (décision Q9). Anti-doublon par l'historique `envois`,
  `UNIQUE (evenement_id, commande_id)` (CA3) : l'envoi est inscrit avant l'appel SMTP, dans la
  transaction du consommateur ; un échec SMTP lève une exception (rollback, nouvel essai, Q7).
"""

import io
import logging
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Protocol
from uuid import UUID

import segno

from commun.evenements import Evenement

journal = logging.getLogger(__name__)

EVENEMENT_COMMANDE_CONFIRMEE = "ticketing.order.confirmed"
EVENEMENT_BILLET_EMIS = "ticketing.ticket.issued"
# Files durables des consommateurs (messages_traites.consommateur, DLQ <nom>.dlq), H5.
CONSOMMATEUR_COMMANDE_CONFIRMEE = "notifications.order-confirmed"
CONSOMMATEUR_BILLET_EMIS = "notifications.ticket-issued"


@dataclass(frozen=True)
class Destinataire:
    """Destinataire d'une commande ; `email` None pour un revendeur."""

    commande_id: UUID
    email: str | None
    seance_id: UUID


@dataclass(frozen=True)
class BilletEmis:
    """`data` de ticketing.ticket.issued v1."""

    billet_id: UUID
    commande_id: UUID
    seance_id: UUID
    place_id: UUID
    qr_code: str
    emis_le: datetime


@dataclass(frozen=True)
class Envoi:
    """Ligne de l'historique d'envoi."""

    evenement_id: UUID
    type_evenement: str
    commande_id: UUID
    destinataire: str
    envoye_le: datetime


class DonneesInvalides(ValueError):
    """`data` d'un événement inexploitable : trois tentatives, puis file d'erreur."""


class CommandeInconnue(LookupError):
    """`ticket.issued` d'une commande dont `order.confirmed` n'est pas encore reçu : nouvel
    essai, puis file d'erreur (décision Q11)."""

    def __init__(self, commande_id: UUID) -> None:
        super().__init__(f"Commande {commande_id} inconnue de notifications")
        self.commande_id = commande_id


class DepotNotifications(Protocol):
    """Destinataires et historique d'envoi, dans la transaction du consommateur."""

    async def enregistrer_destinataire(self, destinataire: Destinataire) -> None:
        """Enregistre le destinataire ; une commande déjà connue est ignorée."""
        ...

    async def lire_destinataire(self, commande_id: UUID) -> Destinataire | None:
        """Le destinataire de la commande, ou None si `order.confirmed` n'est pas reçu."""
        ...

    async def inscrire_envoi(self, envoi: Envoi) -> bool:
        """Inscrit l'envoi ; faux si (evenement_id, commande_id) est déjà inscrit."""
        ...


class Envoyeur(Protocol):
    """Port SMTP : lève `OSError` ou `smtplib.SMTPException` si l'envoi échoue."""

    async def envoyer(self, message: EmailMessage) -> None: ...


def destinataire_de_commande(data: dict[str, Any]) -> Destinataire:
    """Lit `data` de ticketing.order.confirmed ; lève `DonneesInvalides`."""
    try:
        commande_id = UUID(str(data["commande_id"]))
        seance_id = UUID(str(data["seance_id"]))
        email = data["email"]
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesInvalides(f"Commande confirmée invalide : {erreur!r}") from erreur
    if email is not None and (not isinstance(email, str) or not email):
        raise DonneesInvalides("Commande confirmée invalide : email illisible")
    return Destinataire(commande_id=commande_id, email=email, seance_id=seance_id)


def billet_emis(data: dict[str, Any]) -> BilletEmis:
    """Lit `data` de ticketing.ticket.issued ; lève `DonneesInvalides`."""
    try:
        billet = BilletEmis(
            billet_id=UUID(str(data["billet_id"])),
            commande_id=UUID(str(data["commande_id"])),
            seance_id=UUID(str(data["seance_id"])),
            place_id=UUID(str(data["place_id"])),
            qr_code=data["qr_code"],
            emis_le=datetime.fromisoformat(str(data["emis_le"])),
        )
    except (KeyError, TypeError, ValueError) as erreur:
        raise DonneesInvalides(f"Billet émis invalide : {erreur!r}") from erreur
    if not isinstance(billet.qr_code, str) or not billet.qr_code:
        raise DonneesInvalides("Billet émis invalide : qr_code vide")
    return billet


def image_qr(contenu: str) -> bytes:
    """Image PNG du QR code."""
    tampon = io.BytesIO()
    segno.make(contenu, error="m").save(tampon, kind="png", scale=8, border=4)
    return tampon.getvalue()


def message_du_billet(billet: BilletEmis, destinataire: str, expediteur: str) -> EmailMessage:
    """E-mail du billet : QR joint en PNG, contenu du QR dans le corps texte."""
    message = EmailMessage()
    message["Subject"] = "Votre billet"
    message["From"] = expediteur
    message["To"] = destinataire
    message.set_content(
        "Bonjour,\n\n"
        "Votre paiement est confirmé. Votre billet est joint à ce message (QR code à présenter "
        "à l'entrée).\n\n"
        f"Billet : {billet.billet_id}\n"
        f"Contenu du QR code : {billet.qr_code}\n"
    )
    message.add_attachment(
        image_qr(billet.qr_code),
        maintype="image",
        subtype="png",
        filename=f"billet-{billet.billet_id}.png",
    )
    return message


async def enregistrer_destinataire(depot: DepotNotifications, evenement: Evenement) -> None:
    """Traitement de ticketing.order.confirmed."""
    await depot.enregistrer_destinataire(destinataire_de_commande(evenement.data))


async def envoyer_billet(
    depot: DepotNotifications,
    envoyeur: Envoyeur,
    evenement: Evenement,
    *,
    expediteur: str,
    maintenant: datetime,
) -> None:
    """Traitement de ticketing.ticket.issued : inscrit l'envoi puis envoie l'e-mail.

    Commande inconnue : `CommandeInconnue` ; destinataire sans e-mail : rien ; envoi déjà
    inscrit : rien ; échec SMTP : l'exception remonte.
    """
    billet = billet_emis(evenement.data)
    destinataire = await depot.lire_destinataire(billet.commande_id)
    if destinataire is None:
        raise CommandeInconnue(billet.commande_id)
    if destinataire.email is None:
        # Commande de revendeur : rien à envoyer.
        journal.info(
            "Billet %s de la commande %s : revendeur, aucun e-mail",
            billet.billet_id,
            billet.commande_id,
        )
        return
    # Inscription d'abord (ON CONFLICT DO NOTHING) : un traitement concurrent du même
    # événement attend ici le commit du premier, puis n'envoie rien (décision Q7).
    nouveau = await depot.inscrire_envoi(
        Envoi(
            evenement_id=evenement.id,
            type_evenement=evenement.type,
            commande_id=billet.commande_id,
            destinataire=destinataire.email,
            envoye_le=maintenant,
        )
    )
    if not nouveau:
        journal.info(
            "E-mail du billet %s (commande %s) déjà envoyé, ignoré",
            billet.billet_id,
            billet.commande_id,
        )
        return
    await envoyeur.envoyer(message_du_billet(billet, destinataire.email, expediteur))
    # Jamais l'adresse dans les journaux (rules/securite.md) : identifiants seulement.
    journal.info("E-mail du billet %s envoyé (commande %s)", billet.billet_id, billet.commande_id)
