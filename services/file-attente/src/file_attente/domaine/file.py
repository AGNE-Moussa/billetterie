"""Règles de la file d'attente virtuelle (BIL-015), sans Redis.

- Une file par séance sous file (`SEANCES_SOUS_FILE`) ; hors liste : 404 QUEUE_NOT_FOUND.
- Entrée idempotente : un client déjà présent garde sa place (ou son admission).
- Position 1 pour le prochain admis ; attente estimée `ceil(position / taille) × intervalle`.
- Admission par vagues (tâche périodique) ; un admis reçoit un jeton signé, le même à chaque
  lecture, valable jusqu'à l'échéance de l'admission. À l'échéance, il sort de la file.

Le stockage (`StockageFile`) garantit l'atomicité de chaque opération ; ici, seulement les règles
et la mise en forme du résultat.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from commun.admission import signer_admission
from commun.erreurs import ErreurMetier


class StatutFile(StrEnum):
    EN_ATTENTE = "EN_ATTENTE"
    ADMIS = "ADMIS"


# Description du schéma StatutFile du contrat (Pydantic la lit dans __doc__, sur une ligne).
StatutFile.__doc__ = (
    "EN_ATTENTE : l'appelant attend son tour. ADMIS : admis par une vague, il peut commander"
    " avec son jeton d'admission jusqu'à admission_expire_le."
)


class FileIntrouvable(ErreurMetier):
    def __init__(self, seance_id: UUID) -> None:
        super().__init__(
            "QUEUE_NOT_FOUND", 404, f"Aucune file d'attente pour la séance {seance_id}."
        )


class PositionIntrouvable(ErreurMetier):
    def __init__(self, seance_id: UUID) -> None:
        super().__init__(
            "QUEUE_POSITION_NOT_FOUND",
            404,
            f"L'appelant n'est pas dans la file d'attente de la séance {seance_id}.",
        )


class FileIndisponible(ErreurMetier):
    def __init__(self) -> None:
        super().__init__(
            "FILE_INDISPONIBLE",
            503,
            "La file d'attente ne répond pas ; réessayer dans quelques instants.",
            titre="File indisponible",
        )


@dataclass(frozen=True)
class EtatStocke:
    """État d'un client dans le stockage : rang (0 pour le prochain admis) ou échéance."""

    statut: StatutFile
    rang: int | None = None
    admission_expire_le: datetime | None = None


@dataclass(frozen=True)
class PositionFile:
    seance_id: UUID
    statut: StatutFile
    position: int | None
    attente_estimee_secondes: int | None
    jeton_admission: str | None
    admission_expire_le: datetime | None


@dataclass(frozen=True)
class ReglesFile:
    seances_sous_file: frozenset[UUID]
    taille_vague: int
    intervalle_vagues: float
    cle_signature: str


class StockageFile(Protocol):
    """Opérations atomiques sur la file ; Redis injoignable : `FileIndisponible`."""

    async def entrer(self, seance_id: UUID, sub: str) -> tuple[EtatStocke, bool]:
        """État de `sub` après entrée, et vrai s'il vient d'entrer en fin de file."""
        ...

    async def lire(self, seance_id: UUID, sub: str) -> EtatStocke | None:
        """État de `sub`, None s'il n'est pas dans la file (ni en attente, ni admis)."""
        ...


def estimer_attente(position: int, taille_vague: int, intervalle_vagues: float) -> int:
    """Attente estimée en secondes : nombre de vagues avant son tour, fois l'intervalle."""
    return math.ceil(math.ceil(position / taille_vague) * intervalle_vagues)


def _verifier_seance(regles: ReglesFile, seance_id: UUID) -> None:
    if seance_id not in regles.seances_sous_file:
        raise FileIntrouvable(seance_id)


def _position(regles: ReglesFile, seance_id: UUID, sub: str, etat: EtatStocke) -> PositionFile:
    if etat.statut is StatutFile.ADMIS:
        assert etat.admission_expire_le is not None
        return PositionFile(
            seance_id=seance_id,
            statut=StatutFile.ADMIS,
            position=None,
            attente_estimee_secondes=None,
            jeton_admission=signer_admission(
                seance_id, sub, etat.admission_expire_le, regles.cle_signature
            ),
            admission_expire_le=etat.admission_expire_le,
        )
    assert etat.rang is not None
    position = etat.rang + 1
    return PositionFile(
        seance_id=seance_id,
        statut=StatutFile.EN_ATTENTE,
        position=position,
        attente_estimee_secondes=estimer_attente(
            position, regles.taille_vague, regles.intervalle_vagues
        ),
        jeton_admission=None,
        admission_expire_le=None,
    )


async def entrer_file(
    stockage: StockageFile, regles: ReglesFile, seance_id: UUID, sub: str
) -> tuple[PositionFile, bool]:
    """Position de `sub` après son entrée, et vrai s'il vient d'entrer (201) plutôt que d'y
    être déjà (200)."""
    _verifier_seance(regles, seance_id)
    etat, entre = await stockage.entrer(seance_id, sub)
    return _position(regles, seance_id, sub, etat), entre


async def lire_position(
    stockage: StockageFile, regles: ReglesFile, seance_id: UUID, sub: str
) -> PositionFile:
    _verifier_seance(regles, seance_id)
    etat = await stockage.lire(seance_id, sub)
    if etat is None:
        raise PositionIntrouvable(seance_id)
    return _position(regles, seance_id, sub, etat)
