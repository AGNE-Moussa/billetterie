"""Jeton d'admission de la file d'attente virtuelle (BIL-015).

Émis par file-attente quand une vague admet un client, vérifié localement par Commandes
(`creerCommande`, en-tête `X-Admission-Token`) : aucun appel réseau entre les deux services,
seule la clé `ADMISSION_CLE_SIGNATURE` est partagée.

Format : `<charge>.<signature>`, où `charge` est `<seance_id>|<sub>|<expiration>` (expiration en
secondes depuis l'époque Unix) encodée en base64url sans remplissage, et `signature` le
HMAC-SHA256 de `charge`, en base64url sans remplissage. Le jeton est déterministe : la même
admission donne toujours le même jeton (file-attente le recalcule à chaque lecture).
"""

import base64
import binascii
import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID

# Longueur minimale de la clé de signature (comme la clé des QR codes).
LONGUEUR_MIN_CLE = 32
# Séparateurs : entre la charge et sa signature, entre les champs de la charge.
SEPARATEUR = "."
SEPARATEUR_CHAMPS = "|"


class AdmissionInvalide(ValueError):
    """Jeton illisible, mal signé, expiré, ou émis pour une autre séance ou un autre appelant."""


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def _deb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def _signature(charge: str, cle: str) -> str:
    if len(cle) < LONGUEUR_MIN_CLE:
        # Erreur de configuration, jamais un jeton signé ou accepté avec une clé faible.
        raise RuntimeError(f"Clé d'admission absente ou de moins de {LONGUEUR_MIN_CLE} caractères")
    return _b64(hmac.new(cle.encode(), charge.encode(), hashlib.sha256).digest())


def signer_admission(seance_id: UUID, sub: str, expire_le: datetime, cle: str) -> str:
    """Jeton d'admission de `sub` pour `seance_id`, valable jusqu'à `expire_le` (à la seconde)."""
    expiration = int(expire_le.timestamp())
    charge = _b64(SEPARATEUR_CHAMPS.join((str(seance_id), sub, str(expiration))).encode())
    return f"{charge}{SEPARATEUR}{_signature(charge, cle)}"


def verifier_admission(
    jeton: str, *, seance_id: UUID, sub: str, maintenant: datetime, cle: str
) -> datetime:
    """Échéance du jeton s'il est bien signé, pour cette séance et cet appelant, et non expiré ;
    sinon `AdmissionInvalide`."""
    charge, separateur, signature = jeton.partition(SEPARATEUR)
    if not separateur or not charge or not signature:
        raise AdmissionInvalide("Jeton d'admission illisible")
    # Comparaison à temps constant, avant toute lecture de la charge.
    if not hmac.compare_digest(_signature(charge, cle).encode(), signature.encode()):
        raise AdmissionInvalide("Signature du jeton d'admission invalide")
    try:
        champs = _deb64(charge).decode().split(SEPARATEUR_CHAMPS)
        seance_texte, sub_jeton, expiration_texte = champs
        seance_jeton = UUID(seance_texte)
        expire_le = datetime.fromtimestamp(int(expiration_texte), UTC)
    except (ValueError, binascii.Error, UnicodeDecodeError) as erreur:
        raise AdmissionInvalide("Charge du jeton d'admission illisible") from erreur
    if seance_jeton != seance_id:
        raise AdmissionInvalide("Jeton d'admission émis pour une autre séance")
    if not hmac.compare_digest(sub_jeton.encode(), sub.encode()):
        raise AdmissionInvalide("Jeton d'admission émis pour un autre appelant")
    if expire_le <= maintenant:
        raise AdmissionInvalide("Jeton d'admission expiré")
    return expire_le
