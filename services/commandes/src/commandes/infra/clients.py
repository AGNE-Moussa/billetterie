"""Clients HTTP de Billets, Catalogue et Paiements (réalisation de `domaine.services`).

Chacun enveloppe un `commun.http.ClientService` (le seul client HTTP autorisé entre services,
contrainte de BIL-008) qui passe par la gateway avec le jeton de service. Les tests unitaires
leur donnent un `ClientService` sur `httpx.MockTransport`.

Les Problem Details reçus sont traduits en erreurs du domaine par leur `code` ; une réponse
hors contrat est journalisée (statut et code seulement, jamais le corps envoyé, qui porte la
carte) et devient `ServiceIndisponible` (503 SERVICE_INDISPONIBLE).
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx

from commandes.domaine.commandes import (
    PaiementDejaExistant,
    PaiementRefuse,
    PlaceDejaPrise,
    PlaceIntrouvable,
    SeanceAnnulee,
)
from commandes.domaine.services import PaiementEnregistre, PaiementLu, SeanceLue, VerrouPlace
from commun.http import ClientService, ServiceIndisponible

journal = logging.getLogger(__name__)

# Noms des cibles (disjoncteurs, messages de ServiceIndisponible).
CIBLE_BILLETS = "billets"
CIBLE_CATALOGUE = "catalogue"
CIBLE_PAIEMENTS = "paiements"


def _code(reponse: httpx.Response) -> str | None:
    """Code stable d'un Problem Details, ou None si le corps n'en est pas un."""
    try:
        corps = reponse.json()
    except ValueError:
        return None
    code = corps.get("code") if isinstance(corps, dict) else None
    return str(code) if code is not None else None


def _corps(reponse: httpx.Response, cible: str) -> dict[str, Any]:
    try:
        corps = reponse.json()
    except ValueError as erreur:
        journal.warning("Réponse illisible de %s (statut %s)", cible, reponse.status_code)
        raise ServiceIndisponible(cible) from erreur
    if not isinstance(corps, dict):
        journal.warning("Réponse inattendue de %s (statut %s)", cible, reponse.status_code)
        raise ServiceIndisponible(cible)
    return corps


def _hors_contrat(reponse: httpx.Response, cible: str) -> ServiceIndisponible:
    journal.warning(
        "Réponse hors contrat de %s : statut %s, code %s",
        cible,
        reponse.status_code,
        _code(reponse),
    )
    return ServiceIndisponible(cible)


class ClientCatalogueHttp:
    def __init__(self, client: ClientService) -> None:
        self._client = client

    async def lire_seance(self, seance_id: UUID) -> SeanceLue | None:
        reponse = await self._client.get(f"/api/v1/shows/{seance_id}")
        if reponse.status_code == 404 and _code(reponse) == "SHOW_NOT_FOUND":
            return None
        if reponse.status_code != 200:
            raise _hors_contrat(reponse, CIBLE_CATALOGUE)
        corps = _corps(reponse, CIBLE_CATALOGUE)
        try:
            return SeanceLue(
                id=UUID(str(corps["id"])),
                debut=datetime.fromisoformat(str(corps["debut"])),
                annulee=bool(corps["annulee"]),
                prix_par_categorie={
                    UUID(str(categorie["id"])): int(categorie["prix"])
                    for categorie in corps["categories"]
                },
            )
        except (KeyError, TypeError, ValueError) as erreur:
            journal.warning("Séance hors contrat reçue de %s", CIBLE_CATALOGUE)
            raise ServiceIndisponible(CIBLE_CATALOGUE) from erreur


class ClientBilletsHttp:
    def __init__(self, client: ClientService) -> None:
        self._client = client

    async def verrouiller_place(
        self, place_id: UUID, *, seance_id: UUID, commande_id: UUID, confirmation: bool
    ) -> VerrouPlace:
        reponse = await self._client.put(
            f"/api/v1/seats/{place_id}/lock",
            json={
                "seance_id": str(seance_id),
                "commande_id": str(commande_id),
                "confirmation": confirmation,
            },
        )
        code = _code(reponse)
        if reponse.status_code == 409 and code == "SEAT_ALREADY_TAKEN":
            raise PlaceDejaPrise(place_id)
        if reponse.status_code == 404 and code == "SEAT_NOT_FOUND":
            raise PlaceIntrouvable(place_id)
        if reponse.status_code != 200:
            raise _hors_contrat(reponse, CIBLE_BILLETS)
        corps = _corps(reponse, CIBLE_BILLETS)
        try:
            return VerrouPlace(
                place_id=UUID(str(corps["place_id"])),
                seance_id=UUID(str(corps["seance_id"])),
                categorie_id=UUID(str(corps["categorie_id"])),
                commande_id=UUID(str(corps["commande_id"])),
                expire_le=datetime.fromisoformat(str(corps["expire_le"])),
            )
        except (KeyError, TypeError, ValueError) as erreur:
            journal.warning("Verrou hors contrat reçu de %s", CIBLE_BILLETS)
            raise ServiceIndisponible(CIBLE_BILLETS) from erreur


class ClientPaiementsHttp:
    def __init__(self, client: ClientService) -> None:
        self._client = client

    async def payer(
        self, *, commande_id: UUID, seance_id: UUID, montant: int, carte_test: str
    ) -> PaiementEnregistre:
        # Idempotency-Key = commande_id (décision Q6) : ClientService rejoue la requête sur un
        # échec transitoire sans risque de second débit.
        reponse = await self._client.post(
            "/api/v1/payments",
            cle_idempotence=str(commande_id),
            json={
                "commande_id": str(commande_id),
                "seance_id": str(seance_id),
                "montant": montant,
                "carte_test": carte_test,
            },
        )
        code = _code(reponse)
        if reponse.status_code == 402 and code == "PAYMENT_REFUSED":
            raise PaiementRefuse()
        if reponse.status_code == 409 and code == "SHOW_CANCELLED":
            raise SeanceAnnulee(seance_id)
        if reponse.status_code == 409 and code == "PAYMENT_ALREADY_EXISTS":
            raise PaiementDejaExistant(commande_id)
        if reponse.status_code != 201:
            raise _hors_contrat(reponse, CIBLE_PAIEMENTS)
        corps = _corps(reponse, CIBLE_PAIEMENTS)
        try:
            return PaiementEnregistre(
                id=UUID(str(corps["id"])),
                commande_id=UUID(str(corps["commande_id"])),
                seance_id=UUID(str(corps["seance_id"])),
                montant=int(corps["montant"]),
            )
        except (KeyError, TypeError, ValueError) as erreur:
            journal.warning("Paiement hors contrat reçu de %s", CIBLE_PAIEMENTS)
            raise ServiceIndisponible(CIBLE_PAIEMENTS) from erreur

    async def lire(self, commande_id: UUID) -> PaiementLu | None:
        # Lecture seule (lirePaiement) : un rejeu par ClientService ne peut créer aucun débit.
        reponse = await self._client.get(f"/api/v1/payments/{commande_id}")
        if reponse.status_code == 404 and _code(reponse) == "PAYMENT_NOT_FOUND":
            return None
        if reponse.status_code != 200:
            raise _hors_contrat(reponse, CIBLE_PAIEMENTS)
        corps = _corps(reponse, CIBLE_PAIEMENTS)
        try:
            return PaiementLu(
                commande_id=UUID(str(corps["commande_id"])), statut=str(corps["statut"])
            )
        except (KeyError, TypeError, ValueError) as erreur:
            journal.warning("Paiement hors contrat reçu de %s", CIBLE_PAIEMENTS)
            raise ServiceIndisponible(CIBLE_PAIEMENTS) from erreur
