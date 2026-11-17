"""Contenu signé du QR code d'un billet (rules/billets-qr.md, décision Q6 de BIL-009).

Format : `<billet_id>.<signature>`, signature HMAC-SHA256 de l'identifiant, en base64url sans
remplissage. Le QR ne porte aucune donnée lisible (nom, place, prix). La clé vient de
`QR_CLE_SIGNATURE` (au moins 32 caractères) ; `verifier_qr` ne lit pas la base : le refus d'un
billet annulé ou déjà scanné relève de la route de scan (V3, H3).
"""

import base64
import hashlib
import hmac
import os
from uuid import UUID

# Longueur minimale de la clé de signature (décision Q6).
LONGUEUR_MIN_CLE = 32
# Séparateur entre l'identifiant du billet et sa signature.
SEPARATEUR = "."
# Variable d'environnement de la clé.
VARIABLE_CLE = "QR_CLE_SIGNATURE"


class QrInvalide(ValueError):
    """Contenu de QR illisible, ou signature qui ne correspond pas à l'identifiant."""


class CleQrAbsente(RuntimeError):
    """`QR_CLE_SIGNATURE` absente ou trop courte : erreur de configuration, jamais un QR
    signé avec une clé faible."""


def _cle(cle: str | None) -> bytes:
    # Lue à chaque appel (pas de cache) : la clé de l'environnement fait foi.
    valeur = os.environ.get(VARIABLE_CLE, "") if cle is None else cle
    if len(valeur) < LONGUEUR_MIN_CLE:
        raise CleQrAbsente(f"{VARIABLE_CLE} absente ou de moins de {LONGUEUR_MIN_CLE} caractères")
    return valeur.encode()


def signer(billet_id: UUID, cle: str | None = None) -> str:
    """Signature HMAC-SHA256 de l'identifiant, en base64url sans remplissage.

    `cle` : clé de signature ; None la lit dans `QR_CLE_SIGNATURE`.
    """
    empreinte = hmac.new(_cle(cle), str(billet_id).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(empreinte).rstrip(b"=").decode()


def contenu_qr(billet_id: UUID, cle: str | None = None) -> str:
    """Contenu du QR code : `<billet_id>.<signature>`."""
    return f"{billet_id}{SEPARATEUR}{signer(billet_id, cle)}"


def verifier_qr(contenu: str, cle: str | None = None) -> UUID:
    """Identifiant du billet si la signature, recalculée, correspond ; sinon `QrInvalide`."""
    identifiant, separateur, signature = contenu.partition(SEPARATEUR)
    if not separateur or not signature:
        raise QrInvalide("QR sans signature")
    try:
        billet_id = UUID(identifiant)
    except ValueError as erreur:
        raise QrInvalide("Identifiant de billet illisible") from erreur
    # Forme canonique exigée : un identifiant écrit autrement (majuscules, accolades) est refusé.
    if str(billet_id) != identifiant:
        raise QrInvalide("Identifiant de billet non canonique")
    # Comparaison à temps constant.
    if not hmac.compare_digest(signer(billet_id, cle).encode(), signature.encode()):
        raise QrInvalide("Signature du QR invalide")
    return billet_id
