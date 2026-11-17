"""BIL-010, CA2 et CA1 (démarrage) : une seule exécution de la tâche par cycle grâce au verrou
Redis `commandes:tache:expiration` (décisions Q1 et Q2), et tâche démarrée par le lifespan
(plan docs/test-plans/BIL-010.md).

Vrai Redis et vraie base ; deux instances = deux `TacheExpiration` (`commandes-1`,
`commandes-2`) sur la même base et le même Redis (conftest : `un_cycle`).
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import pytest

from commandes.config import Parametres
from commandes.principal import creer_app
from commun.faux_jetons import EmetteurDeTest

pytestmark = pytest.mark.anyio

EXPIREE = "ticketing.order.expired"
# Fenêtre assez longue pour que le second cycle tombe dans la même période que le premier.
PERIODE_LONGUE = 10.0
# CA1 : commande dépassée expirée en moins de 3 s par la tâche démarrée avec l'application.
ECHEANCE_DEMARRAGE = 3.0
DELAI_ARRET = 10.0


def depassee() -> datetime:
    return datetime.now(UTC) - timedelta(seconds=1)


@pytest.mark.concurrence
async def test_deux_instances_lancees_ensemble_n_executent_la_tache_qu_une_fois(
    bases: Any, redis: Any, sessions_commandes: Any, paiements_simules: Any, outils: Any
) -> None:
    commandes = [await bases.ajouter_commande(expire_le=depassee()) for _ in range(5)]

    async def instance(numero: int) -> bool | BaseException:
        resultat: bool | BaseException = await outils.un_cycle(
            sessions_commandes,
            redis.url,
            paiements_simules.client,
            instance=f"commandes-{numero + 1}",
        )
        return resultat

    resultats = await outils.barriere(2, instance)

    statuts = [await bases.statut(c.id) for c in commandes]
    assert statuts == ["EXPIREE"] * 5, f"statuts {statuts}, cycles {resultats!r}"
    assert len(await bases.outbox(EXPIREE)) == 5
    # Compteur d'exécutions : une seule instance a obtenu le verrou du cycle.
    assert sorted(resultats, key=str) == [False, True], resultats


async def test_le_verrou_du_cycle_n_est_pas_relache_en_fin_de_cycle(
    bases: Any, redis: Any, sessions_commandes: Any, paiements_simules: Any, outils: Any
) -> None:
    premiere = await bases.ajouter_commande(expire_le=depassee())
    premier = await outils.un_cycle(
        sessions_commandes,
        redis.url,
        paiements_simules.client,
        instance="commandes-1",
        periode=PERIODE_LONGUE,
    )
    seconde = await bases.ajouter_commande(expire_le=depassee())

    second = await outils.un_cycle(
        sessions_commandes,
        redis.url,
        paiements_simules.client,
        instance="commandes-2",
        periode=PERIODE_LONGUE,
    )

    assert await bases.statut(premiere.id) == "EXPIREE", f"cycle 1 : {premier!r}"
    # commandes-2 ne s'est pas exécutée dans la même fenêtre.
    assert await bases.statut(seconde.id) == "EN_ATTENTE"
    assert await redis.valeur(outils.cle_tache) == "commandes-1"
    assert 0 < await redis.pttl(outils.cle_tache) <= PERIODE_LONGUE * 1000
    assert (premier, second) == (True, False)


async def test_le_verrou_d_une_instance_morte_expire_et_l_autre_reprend_la_tache(
    bases: Any, redis: Any, sessions_commandes: Any, paiements_simules: Any, outils: Any
) -> None:
    periode_ms = int(outils.periode_test * 1000)
    # commandes-1 a pris le verrou puis s'est arrêtée : elle ne revient jamais.
    await redis.poser(outils.cle_tache, "commandes-1", px=periode_ms)
    commande = await bases.ajouter_commande(expire_le=depassee())

    pendant = await outils.un_cycle(
        sessions_commandes, redis.url, paiements_simules.client, instance="commandes-2"
    )
    statut_pendant = await bases.statut(commande.id)
    await anyio.sleep(outils.periode_test + 0.2)
    apres = await outils.un_cycle(
        sessions_commandes, redis.url, paiements_simules.client, instance="commandes-2"
    )

    assert statut_pendant == "EN_ATTENTE", "commandes-2 s'est exécutée sous le verrou d'autrui"
    assert await bases.statut(commande.id) == "EXPIREE", f"cycles : {pendant!r}, {apres!r}"
    assert await redis.valeur(outils.cle_tache) == "commandes-2"
    assert (pendant, apres) == (False, True)


async def test_la_tache_demarre_avec_l_application_et_expire_sans_appel_manuel(
    urls: dict[str, str], redis_url: str, bases: Any, redis: Any, outils: Any
) -> None:
    app = creer_app(
        Parametres(
            database_url=urls["commandes"],
            instance="commandes-1",
            consul_actif=False,
            redis_url=redis_url,
            expiration_periode=outils.periode_test,
        ),
        verificateur_jetons=EmetteurDeTest().verificateur(),
    )
    commande = await bases.ajouter_commande(expire_le=depassee())
    erreur: BaseException | None = None
    statut = "EN_ATTENTE"
    arret = 0.0
    try:
        async with app.router.lifespan_context(app):
            limite = time.monotonic() + ECHEANCE_DEMARRAGE
            while time.monotonic() < limite:
                statut = await bases.statut(commande.id)
                if statut == "EXPIREE":
                    break
                await anyio.sleep(0.2)
            debut_arret = time.monotonic()
        arret = time.monotonic() - debut_arret
    except Exception as exc:  # noqa: BLE001 : rendue après la vérification de l'état
        erreur = exc

    assert statut == "EXPIREE", (
        f"commande {statut} après {ECHEANCE_DEMARRAGE:.0f} s ; lifespan : {erreur!r}"
    )
    assert erreur is None, f"lifespan : {erreur!r}"
    assert arret < DELAI_ARRET, f"arrêt de l'application en {arret:.1f} s"
    # Tâche arrêtée avec l'application : plus aucune expiration.
    await redis.supprimer(outils.cle_tache)
    apres_arret = await bases.ajouter_commande(expire_le=depassee())
    await anyio.sleep(2 * outils.periode_test)
    assert await bases.statut(apres_arret.id) == "EN_ATTENTE"
