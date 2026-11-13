"""BIL-010, CA1, idempotence et CA2 (défense en profondeur) : la tâche d'expiration de Commandes
sur la vraie base migrée (plan docs/test-plans/BIL-010.md, hypothèses H2 à H4).

Un cycle = `commandes.tache.TacheExpiration.cycle()` avec un vrai `VerrouTacheRedis` (conftest :
`un_cycle`). Les commandes sont écrites directement en base (`Bases.ajouter_commande`) ;
Paiements est un double ASGI du contrat (`lirePaiement`) derrière `ClientPaiementsHttp` et
`ClientService`, une gateway de test enregistre chaque appel.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from commandes.domaine.expiration import expirer_commandes_depassees
from commandes.infra.depot import DepotCommandesSql

pytestmark = pytest.mark.anyio

EXPIREE = "ticketing.order.expired"

# Échec injecté dans la vraie base : toute écriture dans `outbox` lève une erreur.
CREER_ECHEC_OUTBOX = (
    "CREATE OR REPLACE FUNCTION echec_outbox_de_test() RETURNS trigger LANGUAGE plpgsql AS"
    " $$ BEGIN RAISE EXCEPTION 'outbox indisponible (test)'; END $$",
    "CREATE TRIGGER echec_outbox_de_test BEFORE INSERT ON outbox FOR EACH ROW"
    " EXECUTE FUNCTION echec_outbox_de_test()",
)
RETIRER_ECHEC_OUTBOX = (
    "DROP TRIGGER IF EXISTS echec_outbox_de_test ON outbox",
    "DROP FUNCTION IF EXISTS echec_outbox_de_test()",
)


def depassee() -> datetime:
    """Échéance dépassée d'une seconde (données du plan)."""
    return datetime.now(UTC) - timedelta(seconds=1)


async def test_la_tache_passe_la_commande_expiree_et_range_l_evenement_dans_la_meme_transaction(
    bases: Any, redis: Any, sessions_commandes: Any, paiements_simules: Any, outils: Any
) -> None:
    commande = await bases.ajouter_commande(expire_le=depassee(), places=2)

    resultat = await outils.un_cycle(sessions_commandes, redis.url, paiements_simules.client)

    assert await bases.statut(commande.id) == "EXPIREE", f"cycle : {resultat!r}"
    expirees = await bases.evenements_de(EXPIREE, str(commande.id))
    assert len(expirees) == 1, expirees
    # Même transaction : la ligne de la commande et celle de l'outbox ont le même xmin.
    assert expirees[0]["xmin"] == await bases.xmin_commande(str(commande.id))
    assert outils.erreurs_evenement(expirees[0]) == []
    data = expirees[0]["data"]
    assert data["seance_id"] == str(commande.seance_id)
    assert sorted(data["place_ids"]) == sorted(str(p) for p in commande.place_ids)
    assert "remboursement_du" not in data, data
    assert resultat is True


async def test_un_echec_de_publication_annule_l_expiration(
    bases: Any, redis: Any, sessions_commandes: Any, paiements_simules: Any, outils: Any
) -> None:
    commande = await bases.ajouter_commande(expire_le=depassee())
    for requete in CREER_ECHEC_OUTBOX:
        await bases.commandes.executer(requete)
    try:
        resultat = await outils.un_cycle(sessions_commandes, redis.url, paiements_simules.client)
    finally:
        for requete in RETIRER_ECHEC_OUTBOX:
            await bases.commandes.executer(requete)

    assert await bases.statut(commande.id) == "EN_ATTENTE"
    assert await bases.outbox() == []
    # H4 : une erreur sur une commande n'interrompt pas le cycle, qui s'est bien exécuté.
    assert resultat is True, f"cycle : {resultat!r}"


async def test_la_tache_lit_le_vrai_paiement_accepte_et_pose_remboursement_du(
    bases: Any, redis: Any, sessions_commandes: Any, paiements_simules: Any, outils: Any
) -> None:
    commande = await bases.ajouter_commande(expire_le=depassee(), paiement_demande=True)
    paiements_simules.double.statuts[str(commande.id)] = "ACCEPTE"

    resultat = await outils.un_cycle(sessions_commandes, redis.url, paiements_simules.client)

    assert await bases.statut(commande.id) == "EXPIREE", f"cycle : {resultat!r}"
    expirees = await bases.evenements_de(EXPIREE, str(commande.id))
    assert len(expirees) == 1, expirees
    assert outils.erreurs_evenement(expirees[0]) == []
    assert expirees[0]["data"].get("remboursement_du") is True, expirees[0]["data"]
    lectures = paiements_simules.appels("GET")
    assert [a.chemin for a in lectures] == [f"{outils.route_paiements}/{commande.id}"]
    assert paiements_simules.appels("POST") == [], "la tâche a posté un paiement"
    assert resultat is True


async def test_paiements_injoignable_en_integration_laisse_la_commande_en_attente(
    bases: Any,
    redis: Any,
    sessions_commandes: Any,
    paiements_simules: Any,
    outils: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    commande = await bases.ajouter_commande(expire_le=depassee(), paiement_demande=True)
    paiements_simules.injoignable()

    resultat = await outils.un_cycle(sessions_commandes, redis.url, paiements_simules.client)

    assert await bases.statut(commande.id) == "EN_ATTENTE"
    assert await bases.outbox() == []
    # La tâche a bien tenté de lire le paiement (H4), sans jamais en poster.
    assert paiements_simules.appels("GET"), "Paiements n'a jamais été appelé"
    assert paiements_simules.appels("POST") == []
    journaux = caplog.text
    for jeton in paiements_simules.jetons:
        assert jeton not in journaux, "jeton de service journalisé"
    assert outils.carte_acceptee not in journaux
    assert resultat is True, f"cycle : {resultat!r}"


async def test_deux_cycles_successifs_ne_publient_qu_une_expiration_par_commande(
    bases: Any, redis: Any, sessions_commandes: Any, paiements_simules: Any, outils: Any
) -> None:
    commande = await bases.ajouter_commande(expire_le=depassee())

    premier = await outils.un_cycle(sessions_commandes, redis.url, paiements_simules.client)
    # Fenêtre suivante : le verrou du cycle a disparu.
    await redis.supprimer(outils.cle_tache)
    second = await outils.un_cycle(sessions_commandes, redis.url, paiements_simules.client)

    assert await bases.statut(commande.id) == "EXPIREE", f"cycles : {premier!r}, {second!r}"
    assert len(await bases.evenements_de(EXPIREE, str(commande.id))) == 1
    assert (premier, second) == (True, True)


@pytest.mark.concurrence
async def test_deux_expirations_simultanees_de_la_meme_commande_ne_publient_qu_un_evenement(
    bases: Any, sessions_commandes: Any, paiements_simules: Any, outils: Any
) -> None:
    commande = await bases.ajouter_commande(expire_le=depassee())
    maintenant = datetime.now(UTC)

    async def expirer(_numero: int) -> int | BaseException:
        # Verrou du cycle contourné : deux dépôts sur deux sessions, en parallèle.
        try:
            async with sessions_commandes() as session:
                return await expirer_commandes_depassees(
                    DepotCommandesSql(session),
                    paiements_simules.client,
                    maintenant,
                    lot=100,
                )
        except Exception as erreur:  # noqa: BLE001 : rendue, l'état est vérifié d'abord
            return erreur

    resultats = await outils.barriere(2, expirer)

    assert await bases.statut(commande.id) == "EXPIREE", f"transitions : {resultats!r}"
    assert len(await bases.evenements_de(EXPIREE, str(commande.id))) == 1
    assert sorted(resultats, key=str) == [0, 1], resultats
