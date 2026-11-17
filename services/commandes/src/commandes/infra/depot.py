"""Dépôt SQL des commandes (réalisation de `domaine.commandes.DepotCommandes`).

Toute méthode qui touche la base traduit une base injoignable (connexion refusée, délai
dépassé, connexion coupée) en `BaseIndisponible` : 503 BASE_INDISPONIBLE, sans détail technique
(comme billets). Un autre refus de la base est journalisé et remonte (500).

Transactions : `transaction()` ouvre un bloc dont les écritures et les événements (outbox)
sont validés ensemble ; une lecture de commande dans ce bloc verrouille sa ligne (FOR UPDATE),
pour qu'une seule requête la fasse changer de statut. Hors bloc, chaque méthode est sa propre
transaction courte : aucune connexion de la session n'est tenue pendant les appels aux autres
services.

Clé d'idempotence (décision Q16) : verrou consultatif pris sur une connexion dédiée, dans une
transaction tenue jusqu'à `liberer_cle`, donc pendant les appels aux autres services ; son
annulation rend le verrou, même si la connexion retourne au pool sans `liberer_cle`. Cette
connexion vient du moteur dédié aux clés (`infra.base.creer_moteur_cles`, review BIL-008,
point 4) : les clés ne peuvent pas affamer le pool des sessions, et une requête qui n'obtient
pas de connexion de clé dans `delai_base` répond 503 BASE_INDISPONIBLE au lieu d'attendre 30 s.
"""

import functools
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import exc as sa_exc
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from commandes.domaine.commandes import (
    CanalCommande,
    Commande,
    LigneCommande,
    PageResultat,
    StatutCommande,
)
from commandes.infra.base import BaseIndisponible, CommandeLigne, LigneCommandeLigne
from commun.evenements import Evenement
from commun.outbox import publier_plus_tard

journal = logging.getLogger(__name__)

# Base injoignable : TimeoutError et ConnectionRefusedError sont des OSError.
ERREURS_CONNEXION: tuple[type[BaseException], ...] = (
    OSError,
    sa_exc.OperationalError,
    sa_exc.InterfaceError,
    sa_exc.TimeoutError,
)
# Toute erreur venue de la base : traduite par `_traduire` (503) ou remontée telle quelle.
ERREURS_BASE: tuple[type[BaseException], ...] = (*ERREURS_CONNEXION, sa_exc.DBAPIError)
# Lignes comptées dans le plafond de billets par client et par séance (décision Q3).
STATUTS_COMPTES = (StatutCommande.EN_ATTENTE.value, StatutCommande.CONFIRMEE.value)

# Deux espaces de clés distincts (PostgreSQL : la forme à deux int4 et la forme bigint ne se
# recouvrent pas) : la clé d'idempotence ne peut jamais bloquer le plafond.
VERROU_CLE = text("SELECT pg_try_advisory_xact_lock(hashtext(:client), hashtext(:cle))")
VERROU_PLAFOND = text("SELECT pg_advisory_xact_lock(hashtextextended(:cle, 0))")


def _traduire(erreur: BaseException) -> BaseException:
    if isinstance(erreur, ERREURS_CONNEXION):
        return BaseIndisponible()
    if isinstance(erreur, sa_exc.DBAPIError) and erreur.connection_invalidated:
        return BaseIndisponible()
    return erreur


def _base_requise[**P, R](
    methode: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    @functools.wraps(methode)
    async def enveloppe(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await methode(*args, **kwargs)
        except ERREURS_BASE as erreur:
            traduite = _traduire(erreur)
            if traduite is erreur:
                journal.exception("Erreur de la base de commandes")
                raise
            raise traduite from erreur

    return enveloppe


def _commande(ligne: CommandeLigne, lignes: list[LigneCommandeLigne]) -> Commande:
    return Commande(
        id=ligne.id,
        client=ligne.client,
        email=ligne.email,
        cle_idempotence=ligne.cle_idempotence,
        seance_id=ligne.seance_id,
        statut=StatutCommande(ligne.statut),
        lignes=tuple(LigneCommande(place_id=p.place_id, montant=p.montant) for p in lignes),
        montant_total=ligne.montant_total,
        cree_le=ligne.cree_le,
        expire_le=ligne.expire_le,
        paiement_demande=ligne.paiement_demande,
        canal=CanalCommande(ligne.canal),
    )


async def _lignes_des_commandes(
    session: AsyncSession, commande_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Any]]:
    """Lignes de chaque commande, par place."""
    par_commande: dict[uuid.UUID, list[Any]] = {i: [] for i in commande_ids}
    if not commande_ids:
        return par_commande
    requete = (
        select(LigneCommandeLigne)
        .where(LigneCommandeLigne.commande_id.in_(commande_ids))
        .order_by(LigneCommandeLigne.commande_id, LigneCommandeLigne.place_id)
        .execution_options(populate_existing=True)
    )
    for ligne in (await session.scalars(requete)).all():
        par_commande[ligne.commande_id].append(ligne)
    return par_commande


class DepotCommandesSql:
    def __init__(self, session: AsyncSession, moteur_cles: AsyncEngine | None = None) -> None:
        """`moteur_cles` : moteur dédié aux clés d'idempotence (`creer_moteur_cles`) ; à défaut,
        celui de la session."""
        self._session = session
        self._moteur_cles = moteur_cles
        self._en_transaction = False
        self._cles: dict[tuple[str, str], AsyncConnection] = {}

    # --- transactions ---------------------------------------------------------------------

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        try:
            async with self._session.begin():
                self._en_transaction = True
                try:
                    yield
                finally:
                    self._en_transaction = False
        except ERREURS_BASE as erreur:
            traduite = _traduire(erreur)
            if traduite is erreur:
                raise
            raise traduite from erreur

    def transaction(self) -> AbstractAsyncContextManager[None]:
        return self._transaction()

    @asynccontextmanager
    async def _unite(self) -> AsyncIterator[None]:
        """Dans `transaction()` : rien de plus ; sinon une transaction courte."""
        if self._en_transaction:
            yield
        else:
            async with self._session.begin():
                yield

    # --- clé d'idempotence ----------------------------------------------------------------

    def _moteur(self) -> AsyncEngine:
        if self._moteur_cles is not None:
            return self._moteur_cles
        moteur = self._session.bind
        if not isinstance(moteur, AsyncEngine):  # pragma: no cover - sessions de principal.py
            raise RuntimeError("La session du dépôt doit être liée à un AsyncEngine")
        return moteur

    @_base_requise
    async def reserver_cle(self, client: str, cle: str) -> bool:
        connexion = await self._moteur().connect()
        try:
            await connexion.begin()
            pris = bool(await connexion.scalar(VERROU_CLE, {"client": client, "cle": cle}))
        except BaseException:
            await connexion.invalidate()
            await connexion.close()
            raise
        if not pris:
            await connexion.rollback()
            await connexion.close()
            return False
        self._cles[(client, cle)] = connexion
        return True

    async def liberer_cle(self, client: str, cle: str) -> None:
        connexion = self._cles.pop((client, cle), None)
        if connexion is None:
            return
        try:
            # Fin de la transaction : le verrou consultatif est rendu.
            await connexion.rollback()
        except ERREURS_BASE:
            # Connexion perdue : le serveur a déjà rendu le verrou avec elle.
            journal.warning("Connexion de la clé d'idempotence perdue", exc_info=True)
            await connexion.invalidate()
        finally:
            await connexion.close()

    # --- plafond --------------------------------------------------------------------------

    @_base_requise
    async def verrouiller_plafond(self, client: str, seance_id: uuid.UUID) -> None:
        async with self._unite():
            await self._session.execute(VERROU_PLAFOND, {"cle": f"{client}:{seance_id}"})

    @_base_requise
    async def compter_billets(self, client: str, seance_id: uuid.UUID) -> int:
        requete = (
            select(func.count())
            .select_from(LigneCommandeLigne)
            .join(CommandeLigne, CommandeLigne.id == LigneCommandeLigne.commande_id)
            .where(
                CommandeLigne.client == client,
                CommandeLigne.seance_id == seance_id,
                CommandeLigne.statut.in_(STATUTS_COMPTES),
            )
        )
        async with self._unite():
            return int(await self._session.scalar(requete) or 0)

    # --- lectures -------------------------------------------------------------------------

    async def _lignes(self, commande_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Any]]:
        return await _lignes_des_commandes(self._session, commande_ids)

    async def _lire(self, *conditions: Any) -> Commande | None:
        requete = select(CommandeLigne).where(*conditions).execution_options(populate_existing=True)
        if self._en_transaction:
            # Ligne verrouillée jusqu'à la fin du bloc : un seul changement de statut à la fois.
            requete = requete.with_for_update()
        ligne = await self._session.scalar(requete)
        if ligne is None:
            return None
        return _commande(ligne, (await self._lignes([ligne.id]))[ligne.id])

    @_base_requise
    async def lire_commande(self, client: str, commande_id: uuid.UUID) -> Commande | None:
        async with self._unite():
            # Filtré par l'appelant : la commande d'un autre est introuvable (règle métier 6).
            return await self._lire(CommandeLigne.id == commande_id, CommandeLigne.client == client)

    @_base_requise
    async def lire_par_cle(self, client: str, cle: str) -> Commande | None:
        async with self._unite():
            return await self._lire(
                CommandeLigne.client == client, CommandeLigne.cle_idempotence == cle
            )

    @_base_requise
    async def lister_commandes(self, client: str, page: int, size: int) -> PageResultat[Commande]:
        async with self._unite():
            total = await self._session.scalar(
                select(func.count())
                .select_from(CommandeLigne)
                .where(CommandeLigne.client == client)
            )
            requete = (
                select(CommandeLigne)
                .where(CommandeLigne.client == client)
                .order_by(CommandeLigne.cree_le.desc(), CommandeLigne.id)
                .offset((page - 1) * size)
                .limit(size)
                .execution_options(populate_existing=True)
            )
            commandes = list((await self._session.scalars(requete)).all())
            lignes = await self._lignes([c.id for c in commandes])
        return PageResultat(
            elements=[_commande(c, lignes[c.id]) for c in commandes], total=int(total or 0)
        )

    @_base_requise
    async def lister_a_expirer(self, maintenant: datetime, limite: int) -> list[Commande]:
        # Sélection sans verrou (index ix_commandes_statut_expire_le) : chaque commande est
        # relue sous FOR UPDATE avant sa transition. expire_le NULL : jamais lue (Q4).
        requete = (
            select(CommandeLigne)
            .where(
                CommandeLigne.statut == StatutCommande.EN_ATTENTE.value,
                CommandeLigne.expire_le.is_not(None),
                CommandeLigne.expire_le <= maintenant,
            )
            .order_by(CommandeLigne.expire_le, CommandeLigne.id)
            .limit(limite)
            .execution_options(populate_existing=True)
        )
        async with self._unite():
            commandes = list((await self._session.scalars(requete)).all())
            lignes = await self._lignes([c.id for c in commandes])
        return [_commande(c, lignes[c.id]) for c in commandes]

    # --- écritures ------------------------------------------------------------------------

    @_base_requise
    async def ajouter_commande(self, commande: Commande) -> None:
        async with self._unite():
            self._session.add(
                CommandeLigne(
                    id=commande.id,
                    client=commande.client,
                    email=commande.email,
                    cle_idempotence=commande.cle_idempotence,
                    seance_id=commande.seance_id,
                    statut=commande.statut.value,
                    montant_total=commande.montant_total,
                    cree_le=commande.cree_le,
                    expire_le=commande.expire_le,
                    paiement_demande=commande.paiement_demande,
                    canal=commande.canal.value,
                )
            )
            # La commande avant ses lignes (fk_lignes_commande_commande).
            await self._session.flush()
            self._session.add_all(
                LigneCommandeLigne(
                    commande_id=commande.id, place_id=ligne.place_id, montant=ligne.montant
                )
                for ligne in commande.lignes
            )
            await self._session.flush()

    @_base_requise
    async def fixer_montants(
        self,
        commande_id: uuid.UUID,
        montants: dict[uuid.UUID, int],
        montant_total: int,
        expire_le: datetime,
    ) -> None:
        async with self._unite():
            for place_id, montant in montants.items():
                await self._session.execute(
                    update(LigneCommandeLigne)
                    .where(
                        LigneCommandeLigne.commande_id == commande_id,
                        LigneCommandeLigne.place_id == place_id,
                    )
                    .values(montant=montant)
                )
            # Transition gardée (review BIL-008, point 1) : seule une commande EN_ATTENTE reçoit
            # son montant et son échéance ; le domaine l'a relue sous FOR UPDATE.
            await self._session.execute(
                update(CommandeLigne)
                .where(
                    CommandeLigne.id == commande_id,
                    CommandeLigne.statut == StatutCommande.EN_ATTENTE.value,
                )
                .values(montant_total=montant_total, expire_le=expire_le)
            )

    @_base_requise
    async def changer_statut(
        self, commande_id: uuid.UUID, statut: StatutCommande, expire_le: datetime | None = None
    ) -> None:
        valeurs: dict[str, Any] = {"statut": statut.value}
        if expire_le is not None:
            valeurs["expire_le"] = expire_le
        if statut is StatutCommande.EN_ATTENTE:
            # Reverrouillage terminé, appel à Paiements imminent (port `changer_statut`) : la
            # commande sera relue dans Paiements avant d'expirer (review BIL-008, point 3).
            valeurs["paiement_demande"] = True
        async with self._unite():
            await self._session.execute(
                update(CommandeLigne).where(CommandeLigne.id == commande_id).values(**valeurs)
            )

    @_base_requise
    async def publier(self, evenement: Evenement) -> None:
        async with self._unite():
            await publier_plus_tard(self._session, evenement)


class DepotAnnulationSql:
    """Réalisation de `domaine.annulation.DepotAnnulation`, dans la session (et la transaction)
    du consommateur (BIL-011)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @_base_requise
    async def commandes_en_attente_de_la_seance(self, seance_id: uuid.UUID) -> list[Commande]:
        # FOR UPDATE, ordre stable par identifiant (pas d'interblocage entre deux livraisons
        # simultanées). READ COMMITTED : une ligne attendue puis passée CONFIRMEE ou EXPIREE par
        # la transaction concurrente est réévaluée et écartée. `expire_le` NULL compris (Q5).
        requete = (
            select(CommandeLigne)
            .where(
                CommandeLigne.seance_id == seance_id,
                CommandeLigne.statut == StatutCommande.EN_ATTENTE.value,
            )
            .order_by(CommandeLigne.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        commandes = list((await self._session.scalars(requete)).all())
        lignes = await _lignes_des_commandes(self._session, [c.id for c in commandes])
        return [_commande(c, lignes[c.id]) for c in commandes]

    @_base_requise
    async def lire_commande_verrouillee(self, commande_id: uuid.UUID) -> Commande | None:
        requete = (
            select(CommandeLigne)
            .where(CommandeLigne.id == commande_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        ligne = await self._session.scalar(requete)
        if ligne is None:
            return None
        lignes = await _lignes_des_commandes(self._session, [ligne.id])
        return _commande(ligne, lignes[ligne.id])

    @_base_requise
    async def changer_statut(self, commande_id: uuid.UUID, statut: StatutCommande) -> None:
        await self._session.execute(
            update(CommandeLigne).where(CommandeLigne.id == commande_id).values(statut=statut.value)
        )

    async def publier(self, evenement: Evenement) -> None:
        await publier_plus_tard(self._session, evenement)
