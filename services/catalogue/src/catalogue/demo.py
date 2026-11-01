"""Jeu de données de démonstration, chargé par `python -m catalogue.demo` (cible `make demo`).

Décision Q17 du plan BIL-004 : les séances passent par le domaine (règles, puis outbox :
chaque séance publie ticketing.show.scheduled), dates relatives au jour du chargement, local
seulement. Décision S2 : chaque élément porte un UUID fixe écrit ici ; un élément dont
l'identifiant existe déjà est sauté, si bien qu'un second chargement ne crée ni doublon ni
événement d'outbox.

Données synthétiques uniquement : villes, lieux et adresses fictifs.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from catalogue.config import Parametres
from catalogue.domaine.catalogue import (
    DepotCatalogue,
    Evenement,
    Lieu,
    NouvelleCategorie,
    NouvelleSeance,
    Rang,
    programmer_seance,
)
from catalogue.infra.base import creer_moteur
from catalogue.infra.depot import DepotCatalogueSql

# Heure de début des séances du jeu (UTC).
HEURE_DES_SEANCES = time(19, 0, tzinfo=UTC)


@dataclass(frozen=True)
class LieuDemo:
    identifiant: UUID
    nom: str
    adresse: str
    ville: str


@dataclass(frozen=True)
class SeanceDemo:
    identifiant: UUID
    lieu: UUID  # identifiant d'un LieuDemo du jeu
    debut: datetime
    categories: list[NouvelleCategorie]


@dataclass(frozen=True)
class EvenementDemo:
    identifiant: UUID
    nom: str
    description: str
    seances: list[SeanceDemo]


@dataclass(frozen=True)
class JeuDemonstration:
    lieux: list[LieuDemo]
    evenements: list[EvenementDemo]


class DepotDemonstration(DepotCatalogue, Protocol):
    """Dépôt qui accepte un identifiant imposé à la création (DepotCatalogueSql)."""

    async def ajouter_evenement(
        self, nom: str, description: str, identifiant: UUID | None = None
    ) -> Evenement: ...

    async def ajouter_lieu(
        self, nom: str, adresse: str, ville: str, identifiant: UUID | None = None
    ) -> Lieu: ...


SALLE_DES_LILAS = UUID("6b1f0c2e-4d5a-4e8b-9c11-0d0e0a000001")
THEATRE_DU_PORT = UUID("6b1f0c2e-4d5a-4e8b-9c11-0d0e0a000002")


def _rangs(*rangs: tuple[str, int]) -> list[Rang]:
    return [Rang(rang=rang, nombre_places=places) for rang, places in rangs]


def _categories(numero: int) -> list[NouvelleCategorie]:
    """Deux catégories aux identifiants fixes, propres à la séance `numero`."""
    return [
        NouvelleCategorie(
            identifiant=UUID(f"6b1f0c2e-4d5a-4e8b-9c11-0d0e0c{numero:04d}01"),
            nom="Fosse",
            prix=4500,
            rangs=_rangs(("A", 20), ("B", 20)),
        ),
        NouvelleCategorie(
            identifiant=UUID(f"6b1f0c2e-4d5a-4e8b-9c11-0d0e0c{numero:04d}02"),
            nom="Balcon",
            prix=3000,
            rangs=_rangs(("C", 15), ("D", 15)),
        ),
    ]


def jeu_de_demonstration(maintenant: datetime) -> JeuDemonstration:
    """Le jeu, avec des débuts de séance relatifs à `maintenant` (jour du chargement)."""

    def dans(jours: int) -> datetime:
        return datetime.combine(maintenant.date() + timedelta(days=jours), HEURE_DES_SEANCES)

    def seance(numero: int, lieu: UUID, jours: int) -> SeanceDemo:
        return SeanceDemo(
            identifiant=UUID(f"6b1f0c2e-4d5a-4e8b-9c11-0d0e0b{numero:06d}"),
            lieu=lieu,
            debut=dans(jours),
            categories=_categories(numero),
        )

    return JeuDemonstration(
        lieux=[
            LieuDemo(
                identifiant=SALLE_DES_LILAS,
                nom="Salle des Lilas",
                adresse="12 rue de l'Exemple",
                ville="Villedemo",
            ),
            LieuDemo(
                identifiant=THEATRE_DU_PORT,
                nom="Théâtre du Port",
                adresse="3 quai de la Démonstration",
                ville="Port-Exemple",
            ),
        ],
        evenements=[
            EvenementDemo(
                identifiant=UUID("6b1f0c2e-4d5a-4e8b-9c11-0d0e0d000001"),
                nom="Concert d'ouverture",
                description="Un concert fictif pour essayer la billetterie.",
                seances=[
                    seance(1, SALLE_DES_LILAS, 14),
                    seance(2, THEATRE_DU_PORT, 21),
                ],
            ),
            EvenementDemo(
                identifiant=UUID("6b1f0c2e-4d5a-4e8b-9c11-0d0e0d000002"),
                nom="La Pièce de démonstration",
                description="Une comédie en trois actes, entièrement imaginaire.",
                seances=[
                    seance(3, THEATRE_DU_PORT, 10),
                    seance(4, THEATRE_DU_PORT, 11),
                ],
            ),
            EvenementDemo(
                identifiant=UUID("6b1f0c2e-4d5a-4e8b-9c11-0d0e0d000003"),
                nom="Soirée jazz",
                description="Un trio de jazz fictif.",
                seances=[seance(5, SALLE_DES_LILAS, 30)],
            ),
            EvenementDemo(
                identifiant=UUID("6b1f0c2e-4d5a-4e8b-9c11-0d0e0d000004"),
                nom="Exposition à venir",
                description="Événement annoncé, sans séance programmée pour l'instant.",
                seances=[],
            ),
        ],
    )


async def charger_jeu_de_demonstration(depot: DepotDemonstration, maintenant: datetime) -> None:
    """Charge le jeu ; un second chargement ne crée ni doublon ni événement d'outbox."""
    jeu = jeu_de_demonstration(maintenant)
    for lieu in jeu.lieux:
        if await depot.trouver_lieu(lieu.identifiant) is None:
            await depot.ajouter_lieu(lieu.nom, lieu.adresse, lieu.ville, lieu.identifiant)
    for evenement in jeu.evenements:
        if await depot.trouver_evenement(evenement.identifiant) is None:
            await depot.ajouter_evenement(
                evenement.nom, evenement.description, evenement.identifiant
            )
        for seance in evenement.seances:
            if await depot.trouver_seance(seance.identifiant) is not None:
                continue
            await programmer_seance(
                depot,
                evenement.identifiant,
                NouvelleSeance(
                    identifiant=seance.identifiant,
                    lieu_id=seance.lieu,
                    debut=seance.debut,
                    categories=seance.categories,
                ),
                maintenant,
            )


async def _charger() -> None:
    config = Parametres()
    moteur = creer_moteur(config.database_url, config.delai_base)
    try:
        async with async_sessionmaker(moteur, expire_on_commit=False)() as session:
            await charger_jeu_de_demonstration(DepotCatalogueSql(session), datetime.now(UTC))
    finally:
        await moteur.dispose()


if __name__ == "__main__":
    asyncio.run(_charger())
