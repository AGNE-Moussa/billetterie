"""E3 (BIL-008, décisions Q12 et Q16) : `Idempotency-Key` de `creerCommande` ; verrou
consultatif de session sur (client, clé) et `UNIQUE (client, cle_idempotence)`, vraie base.
"""

import asyncio
from collections import Counter
from typing import Any

import pytest

pytestmark = pytest.mark.anyio

REQUETES_SIMULTANEES = 5


async def test_rejouer_une_commande_terminee_renvoie_200_sans_nouvelle_commande(
    plateforme: Any, outils: Any
) -> None:
    premiere = await plateforme.commander("A", ["A1"], cle="cle-bil-008-1")
    rejeu = await plateforme.commander("A", ["A1"], cle="cle-bil-008-1")

    corps = outils.exiger_statut(premiere, 201, "première requête")
    assert outils.exiger_statut(rejeu, 200, "rejeu, même clé")["id"] == corps["id"]
    assert len(await plateforme.bases.commandes_de("client-a")) == 1
    assert len(await plateforme.bases.paiements_de()) == 1


async def test_rejouer_pendant_la_premiere_requete_renvoie_409_request_in_progress(
    plateforme: Any, outils: Any
) -> None:
    liberation, arrivee = asyncio.Event(), asyncio.Event()
    plateforme.retenir_paiements(liberation, arrivee)
    premiere = asyncio.create_task(plateforme.commander("A", ["A1"], cle="cle-bil-008-encours"))
    try:
        attente = asyncio.create_task(arrivee.wait())
        await outils.borne(
            "première requête jusqu'à Paiements",
            asyncio.wait({premiere, attente}, return_when=asyncio.FIRST_COMPLETED),
        )
        attente.cancel()
        if premiere.done():
            reponse = premiere.result()
            raise AssertionError(
                f"la première requête a répondu sans appeler Paiements : {reponse.status_code}"
                f" {reponse.text}"
            )

        seconde = await plateforme.commander(
            "A", ["A1"], cle="cle-bil-008-encours", instance=plateforme.commandes_2
        )
    finally:
        liberation.set()
    reponse_premiere = await outils.borne("première requête", premiere)

    outils.exiger_probleme(seconde, 409, "REQUEST_IN_PROGRESS", "seconde requête, même clé")
    outils.exiger_statut(reponse_premiere, 201, "première requête, une fois libérée")
    assert len(await plateforme.bases.commandes_de("client-a")) == 1


async def test_deux_requetes_simultanees_de_meme_cle_ne_creent_qu_une_commande(
    plateforme: Any, outils: Any
) -> None:
    async def appel(numero: int) -> Any:
        return await plateforme.commander(
            "A", ["A1"], cle="cle-bil-008-simultanee", instance=plateforme.instance(numero)
        )

    reponses = await outils.barriere(REQUETES_SIMULTANEES, appel)

    statuts = Counter(reponse.status_code for reponse in reponses)
    assert set(statuts) <= {200, 201, 409}, [r.text for r in reponses]
    assert statuts[201] == 1, statuts
    assert all(r.json()["code"] == "REQUEST_IN_PROGRESS" for r in reponses if r.status_code == 409)
    assert len(await plateforme.bases.commandes_de("client-a")) == 1
    assert len(await plateforme.bases.paiements_de()) == 1
