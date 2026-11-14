"""Contrôle d'admission de la file d'attente virtuelle dans creerCommande (BIL-015).

Pour une séance sous file (`SEANCES_SOUS_FILE`), un client doit présenter dans
`X-Admission-Token` le jeton que file-attente lui a remis : signature, séance, appelant (`sub`)
et expiration vérifiés localement (clé partagée), avant tout verrou. Un revendeur (`partner`)
n'y est pas soumis (risque accepté de BIL-015, quota 429 seulement).
"""

from datetime import datetime
from uuid import UUID

from commun.admission import AdmissionInvalide, verifier_admission
from commun.auth import Appelant
from commun.erreurs import ErreurMetier

ROLE_REVENDEUR = "partner"


class AdmissionRequise(ErreurMetier):
    def __init__(self, seance_id: UUID) -> None:
        super().__init__(
            "ADMISSION_REQUIRED",
            403,
            f"La séance {seance_id} est sous file d'attente : jeton d'admission requis"
            " (X-Admission-Token).",
            titre="Admission requise",
        )


class AdmissionRefusee(ErreurMetier):
    def __init__(self, seance_id: UUID) -> None:
        super().__init__(
            "ADMISSION_INVALID",
            403,
            f"Le jeton d'admission n'est pas valable pour la séance {seance_id} : mal signé,"
            " expiré, ou émis pour une autre séance ou un autre appelant.",
            titre="Admission refusée",
        )


def controler_admission(
    appelant: Appelant,
    seance_id: UUID,
    jeton: str | None,
    *,
    seances_sous_file: frozenset[UUID],
    cle: str,
    maintenant: datetime,
) -> None:
    """Rien si la commande peut continuer ; sinon `AdmissionRequise` ou `AdmissionRefusee`."""
    if seance_id not in seances_sous_file or ROLE_REVENDEUR in appelant.roles:
        return
    if not jeton:
        raise AdmissionRequise(seance_id)
    try:
        verifier_admission(
            jeton, seance_id=seance_id, sub=appelant.identifiant, maintenant=maintenant, cle=cle
        )
    except AdmissionInvalide as erreur:
        raise AdmissionRefusee(seance_id) from erreur
