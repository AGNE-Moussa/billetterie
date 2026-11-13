"""Expiration périodique des commandes non payées (BIL-010), sans SQLAlchemy, httpx ni Redis.

Un cycle (décisions Q1, Q2, Q5 et hypothèses H2 à H4 du plan BIL-010) :

1. prend le verrou de tâche `commandes:tache:expiration` (`SET NX PX`, valeur = instance, durée
   = une période, jamais relâché) ; déjà pris : rien ; Redis injoignable : cycle sauté
   (`WARNING`) ;
2. lit au plus `lot` commandes `EN_ATTENTE` dont `expire_le <= maintenant`, par `expire_le`
   croissant (une commande sans `expire_le` n'est jamais lue, Q4) ;
3. expire chacune avec la logique de BIL-008 (`_expirer` : lecture de Paiements si
   `paiement_demande`, jamais de `POST`), après avoir relu `expire_le` sous `FOR UPDATE` (H3) ;
   une erreur sur une commande n'interrompt pas le cycle.
"""

import logging
from datetime import datetime
from typing import Protocol

from commandes.domaine.commandes import DepotCommandes, expirer_commande_echue
from commandes.domaine.services import ClientPaiements

journal = logging.getLogger(__name__)

# Clé Redis du verrou de la tâche (décision Q1).
CLE_VERROU_TACHE = "commandes:tache:expiration"


class VerrouTacheIndisponible(Exception):
    """Le magasin du verrou de tâche ne répond pas : le cycle est sauté (décision Q2)."""


class VerrouTache(Protocol):
    """Verrou d'exécution de la tâche, partagé par les instances de Commandes."""

    async def prendre(self, cle: str, proprietaire: str, duree_ms: int) -> bool:
        """`SET cle proprietaire NX PX duree_ms` : vrai si le verrou vient d'être posé, faux s'il
        est déjà tenu. Lève `VerrouTacheIndisponible` si le magasin ne répond pas."""
        ...

    async def fermer(self) -> None:
        """Ferme la connexion au magasin."""
        ...


async def expirer_commandes_depassees(
    depot: DepotCommandes,
    paiements: ClientPaiements,
    maintenant: datetime,
    *,
    lot: int,
) -> int:
    """Expire au plus `lot` commandes `EN_ATTENTE` dépassées ; renvoie le nombre expirées."""
    expirees = 0
    for commande in await depot.lister_a_expirer(maintenant, lot):
        try:
            # Logique de BIL-008 : lecture du paiement si demandé, puis transition gardée sous
            # FOR UPDATE, avec l'échéance relue (H3).
            if await expirer_commande_echue(depot, commande, paiements, maintenant):
                expirees += 1
        except Exception:
            # Paiements ou base indisponible pour cette commande : reprise au cycle suivant,
            # sans interrompre le cycle (H4). Aucun jeton ni donnée de carte dans ce journal.
            journal.warning(
                "Commande %s laissée en attente, expiration reprise au cycle suivant",
                commande.id,
                exc_info=True,
            )
    return expirees


async def executer_cycle(
    verrou: VerrouTache,
    depot: DepotCommandes,
    paiements: ClientPaiements,
    maintenant: datetime,
    *,
    instance: str,
    periode: float,
    lot: int,
) -> bool:
    """Un cycle de la tâche ; renvoie vrai si cette instance a obtenu le verrou et l'a exécuté.

    `periode` (secondes) : durée du verrou de tâche.
    """
    try:
        # Jamais relâché : il expire seul à la fin de la fenêtre (décision Q1).
        pris = await verrou.prendre(CLE_VERROU_TACHE, instance, int(periode * 1000))
    except VerrouTacheIndisponible:
        journal.warning("Verrou de la tâche d'expiration injoignable : cycle sauté")
        return False
    if not pris:
        return False
    expirees = await expirer_commandes_depassees(depot, paiements, maintenant, lot=lot)
    if expirees:
        journal.info("Tâche d'expiration (%s) : %d commandes expirées", instance, expirees)
    return True
