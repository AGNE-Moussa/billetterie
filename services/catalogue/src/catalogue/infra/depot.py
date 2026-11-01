"""Dépôt du catalogue sur PostgreSQL.

Toute méthode qui touche la base traduit une base injoignable (connexion refusée, délai
dépassé, connexion coupée) en BaseIndisponible : 503 BASE_INDISPONIBLE, sans détail technique.
Un autre refus de la base devient ErreurBase (500 ERREUR_INTERNE), journalisé avec sa trace.
"""

import functools
import logging
import uuid
from collections.abc import Callable, Coroutine, Sequence
from datetime import UTC
from typing import Any

from sqlalchemy import ColumnElement, Select, exists, func, insert, or_, select
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncSession

from catalogue.domaine.catalogue import (
    EVENEMENT_SEANCE_PROGRAMMEE,
    Categorie,
    Evenement,
    FiltresEvenements,
    Lieu,
    NouvelleSeance,
    Rang,
    Seance,
    donnees_seance_programmee,
)
from catalogue.infra.base import (
    BaseIndisponible,
    CategorieLigne,
    ErreurBase,
    EvenementLigne,
    LieuLigne,
    RangLigne,
    SeanceLigne,
)
from commun.evenements import Evenement as EvenementPublie
from commun.outbox import publier_plus_tard

journal = logging.getLogger(__name__)

# Base injoignable : TimeoutError et ConnectionRefusedError sont des OSError.
ERREURS_CONNEXION: tuple[type[BaseException], ...] = (
    OSError,
    sa_exc.OperationalError,
    sa_exc.InterfaceError,
    sa_exc.TimeoutError,
)


def _base_requise[**P, R](
    methode: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    @functools.wraps(methode)
    async def enveloppe(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await methode(*args, **kwargs)
        except ERREURS_CONNEXION as erreur:
            raise BaseIndisponible() from erreur
        except sa_exc.DBAPIError as erreur:
            if erreur.connection_invalidated:
                raise BaseIndisponible() from erreur
            # Refus imprévu de la base (la transaction est annulée à la fermeture de la
            # session) : trace dans les journaux, 500 Problem Details sans détail au client.
            journal.exception("Erreur de la base du catalogue")
            raise ErreurBase() from erreur

    return enveloppe


def _echapper(texte: str) -> str:
    """Motif LIKE littéral : % et _ saisis par le client ne sont pas des jokers."""
    return texte.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _conditions(filtres: FiltresEvenements) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filtres.q is not None:
        # Sous-chaîne insensible à la casse, dans le nom ou la description (décision Q6).
        motif = f"%{_echapper(filtres.q)}%"
        conditions.append(
            or_(
                EvenementLigne.nom.ilike(motif, escape="\\"),
                EvenementLigne.description.ilike(motif, escape="\\"),
            )
        )
    if filtres.ville is not None or filtres.du is not None or filtres.au is not None:
        # Au moins une séance qui remplit, à elle seule, la ville et l'intervalle (bornes
        # incluses) ; EXISTS : un événement à plusieurs séances n'est compté qu'une fois.
        seance: list[ColumnElement[bool]] = [SeanceLigne.evenement_id == EvenementLigne.id]
        if filtres.ville is not None:
            # Égalité insensible à la casse (décision Q7).
            seance.append(func.lower(LieuLigne.ville) == func.lower(filtres.ville))
        if filtres.du is not None:
            seance.append(SeanceLigne.debut >= filtres.du)
        if filtres.au is not None:
            seance.append(SeanceLigne.debut <= filtres.au)
        conditions.append(
            exists(
                select(SeanceLigne.id)
                .join(LieuLigne, LieuLigne.id == SeanceLigne.lieu_id)
                .where(*seance)
            )
        )
    return conditions


def _evenement(ligne: EvenementLigne) -> Evenement:
    return Evenement(
        id=ligne.id, nom=ligne.nom, description=ligne.description, cree_le=ligne.cree_le
    )


def _lieu(ligne: LieuLigne) -> Lieu:
    return Lieu(
        id=ligne.id,
        nom=ligne.nom,
        adresse=ligne.adresse,
        ville=ligne.ville,
        cree_le=ligne.cree_le,
    )


class DepotCatalogueSql:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- événements -----------------------------------------------------------------------

    @_base_requise
    async def ajouter_evenement(
        self, nom: str, description: str, identifiant: uuid.UUID | None = None
    ) -> Evenement:
        """`identifiant` : imposé par le jeu de démonstration (UUID fixes) ; sinon généré."""
        requete = (
            insert(EvenementLigne)
            .values(id=identifiant or uuid.uuid4(), nom=nom, description=description)
            .returning(EvenementLigne)
        )
        ligne = (await self._session.execute(requete)).scalar_one()
        evenement = _evenement(ligne)
        await self._session.commit()
        return evenement

    @_base_requise
    async def trouver_evenement(self, evenement_id: uuid.UUID) -> Evenement | None:
        ligne = await self._session.get(EvenementLigne, evenement_id)
        return None if ligne is None else _evenement(ligne)

    @_base_requise
    async def lister_evenements(
        self, filtres: FiltresEvenements, decalage: int, limite: int
    ) -> list[Evenement]:
        # Ordre total et stable : création croissante, puis identifiant.
        requete = (
            select(EvenementLigne)
            .where(*_conditions(filtres))
            .order_by(EvenementLigne.cree_le, EvenementLigne.id)
            .offset(decalage)
            .limit(limite)
        )
        lignes = (await self._session.execute(requete)).scalars().all()
        return [_evenement(ligne) for ligne in lignes]

    @_base_requise
    async def compter_evenements(self, filtres: FiltresEvenements) -> int:
        requete = select(func.count()).select_from(EvenementLigne).where(*_conditions(filtres))
        return (await self._session.execute(requete)).scalar_one()

    # --- lieux ----------------------------------------------------------------------------

    @_base_requise
    async def ajouter_lieu(
        self, nom: str, adresse: str, ville: str, identifiant: uuid.UUID | None = None
    ) -> Lieu:
        """`identifiant` : imposé par le jeu de démonstration (UUID fixes) ; sinon généré."""
        requete = (
            insert(LieuLigne)
            .values(id=identifiant or uuid.uuid4(), nom=nom, adresse=adresse, ville=ville)
            .returning(LieuLigne)
        )
        ligne = (await self._session.execute(requete)).scalar_one()
        lieu = _lieu(ligne)
        await self._session.commit()
        return lieu

    @_base_requise
    async def trouver_lieu(self, lieu_id: uuid.UUID) -> Lieu | None:
        ligne = await self._session.get(LieuLigne, lieu_id)
        return None if ligne is None else _lieu(ligne)

    @_base_requise
    async def lister_lieux(self, decalage: int, limite: int) -> list[Lieu]:
        requete = (
            select(LieuLigne)
            .order_by(LieuLigne.cree_le, LieuLigne.id)
            .offset(decalage)
            .limit(limite)
        )
        lignes = (await self._session.execute(requete)).scalars().all()
        return [_lieu(ligne) for ligne in lignes]

    @_base_requise
    async def compter_lieux(self) -> int:
        requete = select(func.count()).select_from(LieuLigne)
        return (await self._session.execute(requete)).scalar_one()

    # --- séances --------------------------------------------------------------------------

    @_base_requise
    async def ajouter_seance(
        self, evenement: Evenement, lieu: Lieu, nouvelle: NouvelleSeance
    ) -> Seance:
        """Séance, catégories, rangs et événement d'outbox dans une seule transaction."""
        seance_id = nouvelle.identifiant or uuid.uuid4()
        # Début en UTC : la réponse 201 et le data de l'outbox ont la même représentation que
        # les lectures, qui relisent la valeur de la base.
        debut = nouvelle.debut.astimezone(UTC)
        await self._session.execute(
            insert(SeanceLigne).values(
                id=seance_id, evenement_id=evenement.id, lieu_id=lieu.id, debut=debut
            )
        )
        categories = [
            Categorie(
                id=nouvelle_categorie.identifiant or uuid.uuid4(),
                nom=nouvelle_categorie.nom,
                prix=nouvelle_categorie.prix,
                rangs=list(nouvelle_categorie.rangs),
            )
            for nouvelle_categorie in nouvelle.categories
        ]
        # Une insertion groupée par table (executemany), dans la transaction de la séance.
        # L'index dans la requête est enregistré (colonne position, décision I1) : l'ordre de
        # relecture ne dépend jamais de l'ordre physique des lignes.
        await self._session.execute(
            insert(CategorieLigne),
            [
                {
                    "id": categorie.id,
                    "seance_id": seance_id,
                    "nom": categorie.nom,
                    "prix": categorie.prix,
                    "position": position_categorie,
                }
                for position_categorie, categorie in enumerate(categories)
            ],
        )
        await self._session.execute(
            insert(RangLigne),
            [
                {
                    "seance_id": seance_id,
                    "rang": rang.rang,
                    "categorie_id": categorie.id,
                    "nombre_places": rang.nombre_places,
                    "position": position_rang,
                }
                for categorie in categories
                for position_rang, rang in enumerate(categorie.rangs)
            ],
        )
        seance = Seance(
            id=seance_id,
            evenement_id=evenement.id,
            lieu_id=lieu.id,
            debut=debut,
            annulee=False,
            categories=categories,
        )
        # Même transaction que la séance : l'événement part si, et seulement si, la séance est
        # enregistrée (décision Q5).
        await publier_plus_tard(
            self._session,
            EvenementPublie.creer(
                EVENEMENT_SEANCE_PROGRAMMEE, donnees_seance_programmee(seance, evenement, lieu)
            ),
        )
        await self._session.commit()
        return seance

    @_base_requise
    async def trouver_seance(self, seance_id: uuid.UUID) -> Seance | None:
        seances = await self._seances(select(SeanceLigne).where(SeanceLigne.id == seance_id))
        return seances[0] if seances else None

    @_base_requise
    async def lister_seances(
        self, evenement_id: uuid.UUID, decalage: int, limite: int
    ) -> list[Seance]:
        # Ordre total et stable : début croissant, puis identifiant.
        return await self._seances(
            select(SeanceLigne)
            .where(SeanceLigne.evenement_id == evenement_id)
            .order_by(SeanceLigne.debut, SeanceLigne.id)
            .offset(decalage)
            .limit(limite)
        )

    @_base_requise
    async def compter_seances(self, evenement_id: uuid.UUID) -> int:
        requete = (
            select(func.count())
            .select_from(SeanceLigne)
            .where(SeanceLigne.evenement_id == evenement_id)
        )
        return (await self._session.execute(requete)).scalar_one()

    async def _seances(self, requete: Select[Any]) -> list[Seance]:
        """Séances de la requête, dans son ordre, avec leurs catégories et leurs rangs."""
        lignes: Sequence[SeanceLigne] = (await self._session.execute(requete)).scalars().all()
        if not lignes:
            return []
        identifiants = [ligne.id for ligne in lignes]
        categories = (
            (
                await self._session.execute(
                    select(CategorieLigne)
                    .where(CategorieLigne.seance_id.in_(identifiants))
                    # Position dans la séance (décision I1) ; les catégories sont ensuite
                    # regroupées par séance.
                    .order_by(CategorieLigne.seance_id, CategorieLigne.position)
                )
            )
            .scalars()
            .all()
        )
        rangs = (
            (
                await self._session.execute(
                    select(RangLigne)
                    .where(RangLigne.seance_id.in_(identifiants))
                    # Position dans la catégorie (décision I1) ; les rangs sont ensuite
                    # regroupés par catégorie.
                    .order_by(RangLigne.categorie_id, RangLigne.position)
                )
            )
            .scalars()
            .all()
        )
        rangs_par_categorie: dict[uuid.UUID, list[Rang]] = {}
        for rang in rangs:
            rangs_par_categorie.setdefault(rang.categorie_id, []).append(
                Rang(rang=rang.rang, nombre_places=rang.nombre_places)
            )
        categories_par_seance: dict[uuid.UUID, list[Categorie]] = {}
        for categorie in categories:
            categories_par_seance.setdefault(categorie.seance_id, []).append(
                Categorie(
                    id=categorie.id,
                    nom=categorie.nom,
                    prix=categorie.prix,
                    rangs=rangs_par_categorie.get(categorie.id, []),
                )
            )
        return [
            Seance(
                id=ligne.id,
                evenement_id=ligne.evenement_id,
                lieu_id=ligne.lieu_id,
                debut=ligne.debut,
                annulee=ligne.annulee,
                categories=categories_par_seance.get(ligne.id, []),
            )
            for ligne in lignes
        ]
