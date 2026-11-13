"""Canal de vente de chaque commande (plan BIL-012, étape « Rattacher chaque commande à son
canal », décision Q3, question 4 du plan, H7).

Le canal est déduit du rôle du jeton (`partner` : PARTENAIRE, sinon DIRECT), gardé en base
seulement : il n'apparaît dans aucune réponse de commande.
"""

from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from commandes.domaine.commandes import CanalCommande, StatutCommande, canal_de
from commun.auth import Appelant
from commun.faux_jetons import EmetteurDeTest

pytestmark = pytest.mark.anyio

ORDERS = "/api/v1/orders"
CARTE_ACCEPTEE = "4242424242424242"
SCOPES_COMMANDES = ["orders:read", "orders:write"]
RACINE = Path(__file__).resolve().parents[4]
CONTRAT_SERVICE = RACINE / "services" / "commandes" / "openapi.yaml"


def _cles_du_schema_commande() -> set[str]:
    contrat: dict[str, Any] = yaml.safe_load(CONTRAT_SERVICE.read_text(encoding="utf-8"))
    return set(contrat["components"]["schemas"]["Commande"]["properties"])


async def test_une_commande_creee_avec_un_jeton_partner_est_rattachee_au_canal_partenaire(
    client: httpx.AsyncClient, seance: Any, entetes_r1: dict[str, str], depot: Any
) -> None:
    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes_r1)

    assert reponse.status_code == 201, reponse.text
    [commande] = depot.commandes_de("sujet-revendeur-test")
    assert commande.canal is CanalCommande.PARTENAIRE
    assert commande.email is None


async def test_une_commande_creee_avec_un_jeton_customer_est_rattachee_au_canal_direct(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], depot: Any
) -> None:
    # Déduction par la règle du domaine, puis commande créée par l'API.
    appelant = Appelant(
        identifiant="client-a",
        roles=frozenset({"customer"}),
        scopes=frozenset(SCOPES_COMMANDES),
        client="frontend",
        email="client.test@exemple.test",
    )
    assert canal_de(appelant) is CanalCommande.DIRECT

    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes_a)

    assert reponse.status_code == 201, reponse.text
    [commande] = depot.commandes_de("client-a")
    assert commande.canal is CanalCommande.DIRECT
    assert commande.email == "client.test@exemple.test"


async def test_un_jeton_a_la_fois_customer_et_partner_donne_le_canal_partenaire(
    client: httpx.AsyncClient, seance: Any, emetteur: EmetteurDeTest, depot: Any
) -> None:
    entetes = emetteur.entetes(
        sujet="sujet-mixte-test",
        roles=["customer", "partner"],
        scopes=SCOPES_COMMANDES,
        client="revendeur-test",
    )

    reponse = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes)

    assert reponse.status_code == 201, reponse.text
    [commande] = depot.commandes_de("sujet-mixte-test")
    assert commande.canal is CanalCommande.PARTENAIRE


async def test_le_canal_n_apparait_dans_aucune_reponse_de_commande(
    client: httpx.AsyncClient,
    seance: Any,
    entetes_r1: dict[str, str],
    depot: Any,
    paiements: Any,
) -> None:
    cles = _cles_du_schema_commande()
    assert "canal" not in cles

    creee = await client.post(ORDERS, json=seance.corps("A1"), headers=entetes_r1)
    # Paiements injoignable : commande EN_ATTENTE (503), payée ensuite par payerCommande.
    paiements.en_panne = True
    en_attente = await client.post(ORDERS, json=seance.corps("A2"), headers=entetes_r1)
    paiements.en_panne = False
    [attente] = [
        c
        for c in depot.commandes_de("sujet-revendeur-test")
        if c.statut is StatutCommande.EN_ATTENTE
    ]
    payee = await client.post(
        f"{ORDERS}/{attente.id}/payment", json={"carte_test": CARTE_ACCEPTEE}, headers=entetes_r1
    )
    liste = await client.get(ORDERS, headers=entetes_r1)
    lue = await client.get(f"{ORDERS}/{creee.json()['id']}", headers=entetes_r1)

    assert creee.status_code == 201, creee.text
    assert en_attente.status_code == 503, en_attente.text
    assert payee.status_code == 200, payee.text
    assert liste.status_code == 200, liste.text
    assert lue.status_code == 200, lue.text
    corps = [creee.json(), payee.json(), lue.json(), *liste.json()["elements"]]
    assert len(corps) == 5
    for commande in corps:
        assert set(commande) == cles
        assert "canal" not in commande


async def test_un_champ_canal_dans_le_corps_ne_change_pas_le_canal_deduit_du_role(
    client: httpx.AsyncClient, seance: Any, entetes_a: dict[str, str], depot: Any
) -> None:
    appelant = Appelant(
        identifiant="client-a",
        roles=frozenset({"customer"}),
        scopes=frozenset(SCOPES_COMMANDES),
        client="frontend",
        email="client.test@exemple.test",
    )
    assert canal_de(appelant) is CanalCommande.DIRECT

    corps = {**seance.corps("A1"), "canal": "PARTENAIRE"}
    reponse = await client.post(ORDERS, json=corps, headers=entetes_a)

    assert reponse.status_code == 201, reponse.text
    [commande] = depot.commandes_de("client-a")
    assert commande.canal is CanalCommande.DIRECT
