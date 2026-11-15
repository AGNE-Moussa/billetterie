"""BIL-015 de bout en bout : file-attente (vrai Redis) remet un jeton d'admission, Commandes
(vraie plateforme : Billets, Paiements, bases migrées) le vérifie dans creerCommande.

La séance S de `plateforme_commandes` est créée après les applications : sa mise sous file
passe par `app.state.parametres` de chaque instance de Commandes (copie des paramètres avec
`seances_sous_file` et la clé partagée), lu à chaque requête par `obtenir_parametres`. Le
service file-attente est démarré avec la même séance, la même clé et le même Redis ; ses
vagues sont lancées par le test (tâche de fond inerte, intervalle d'une heure).

Cas : sans jeton 403 ADMISSION_REQUIRED, jeton valide 201, jeton d'une autre séance ou d'un
autre client 403 ADMISSION_INVALID (aucune commande ni appel à Billets), et régression de
concurrence : deux clients admis sur la même place, un seul 201.
"""

import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from commandes.infra.clients import CIBLE_BILLETS
from file_attente.config import Parametres as ParametresFile
from file_attente.principal import creer_app as creer_file_attente
from file_attente.tache import TacheVagues

pytestmark = pytest.mark.anyio

ROUTE_FILES = "/api/v1/queues"
INTERVALLE_SANS_TACHE = 3600.0


@dataclass
class Montage:
    plateforme: Any
    file: httpx.AsyncClient
    app_file: Any
    seances: frozenset[uuid.UUID]

    async def admettre(self, qui: dict[str, Any], seance_id: uuid.UUID) -> str:
        """Entrée dans la file, une vague, puis lecture du jeton d'admission."""
        entetes = self.plateforme.entetes(qui)
        chemin = f"{ROUTE_FILES}/{seance_id}/position"
        entree = await self.file.post(chemin, headers=entetes)
        assert entree.status_code in (200, 201), f"entrerFile : {entree.text}"
        if entree.json()["statut"] != "ADMIS":
            tache = TacheVagues(
                self.app_file.state.file,
                self.seances,
                instance=f"file-attente-{uuid.uuid4()}",
                taille=100,
                intervalle=0.001,
                duree_admission=600,
            )
            assert await tache.cycle() is True
        lecture = await self.file.get(chemin, headers=self.plateforme.entetes(qui))
        assert lecture.status_code == 200, f"lirePositionFile : {lecture.text}"
        corps = lecture.json()
        assert corps["statut"] == "ADMIS", corps
        return str(corps["jeton_admission"])

    async def commander(
        self,
        qui: dict[str, Any],
        libelles: list[str],
        jeton: str | None,
        *,
        instance: httpx.AsyncClient | None = None,
    ) -> httpx.Response:
        entetes = self.plateforme.entetes(qui)
        if jeton is not None:
            entetes["X-Admission-Token"] = jeton
        corps = {
            "seance_id": str(self.plateforme.seance.id),
            "place_ids": self.plateforme.seance.ids(*libelles),
            "carte_test": "4242424242424242",
        }
        client = instance or self.plateforme.commandes_1
        return await client.post("/api/v1/orders", json=corps, headers=entetes)


@asynccontextmanager
async def _monter(
    plateforme_commandes: Any, redis_url: str, *, autres_seances: int = 0
) -> AsyncIterator[Montage]:
    cle = secrets.token_urlsafe(32)
    async with plateforme_commandes() as plateforme:
        seances = {plateforme.seance.id}
        for _ in range(autres_seances):
            seances.add((await plateforme.nouvelle_seance()).id)
        sous_file = frozenset(seances)
        for app in plateforme.apps_commandes:
            app.state.parametres = app.state.parametres.model_copy(
                update={"seances_sous_file": sous_file, "admission_cle_signature": SecretStr(cle)}
            )
        app_file = creer_file_attente(
            ParametresFile(
                instance="file-attente-test",
                consul_actif=False,
                redis_url=redis_url,
                seances_sous_file=sous_file,
                admission_cle_signature=cle,
                intervalle_vagues=INTERVALLE_SANS_TACHE,
            ),
            verificateur_jetons=plateforme.emetteur.verificateur(),
        )
        async with (
            app_file.router.lifespan_context(app_file),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app_file), base_url="http://test", timeout=60.0
            ) as client_file,
        ):
            yield Montage(plateforme, client_file, app_file, sous_file)


def _client(sujet: str) -> dict[str, Any]:
    return {"sujet": sujet, "roles": ["customer"], "scopes": ["orders:read", "orders:write"]}


async def _aucune_trace(montage: Montage, sujet: str) -> None:
    plateforme = montage.plateforme
    assert await plateforme.bases.commandes_de(sujet) == []
    assert plateforme.gateway.appels_vers(CIBLE_BILLETS) == []


async def test_sans_jeton_d_admission_un_client_recoit_403_admission_required(
    plateforme_commandes: Any, redis_url: str, outils: Any
) -> None:
    async with _monter(plateforme_commandes, redis_url) as montage:
        reponse = await montage.commander(_client("client-sans-jeton"), ["A1"], None)

        outils.exiger_probleme(reponse, 403, "ADMISSION_REQUIRED", "creerCommande sans jeton")
        await _aucune_trace(montage, "client-sans-jeton")


async def test_un_jeton_remis_par_la_file_permet_de_commander(
    plateforme_commandes: Any, redis_url: str, outils: Any
) -> None:
    async with _monter(plateforme_commandes, redis_url) as montage:
        qui = _client("client-admis")
        jeton = await montage.admettre(qui, montage.plateforme.seance.id)

        corps = outils.exiger_statut(
            await montage.commander(qui, ["A1"], jeton), 201, "creerCommande avec jeton"
        )

        assert corps["statut"] == "CONFIRMEE"
        assert await montage.plateforme.bases.statut(corps["id"]) == "CONFIRMEE"


async def test_un_jeton_d_une_autre_seance_est_refuse(
    plateforme_commandes: Any, redis_url: str, outils: Any
) -> None:
    async with _monter(plateforme_commandes, redis_url, autres_seances=1) as montage:
        qui = _client("client-autre-seance")
        autre = next(s for s in montage.seances if s != montage.plateforme.seance.id)
        jeton = await montage.admettre(qui, autre)

        reponse = await montage.commander(qui, ["A1"], jeton)

        outils.exiger_probleme(reponse, 403, "ADMISSION_INVALID", "jeton d'une autre séance")
        await _aucune_trace(montage, "client-autre-seance")


async def test_le_jeton_d_un_autre_client_est_refuse(
    plateforme_commandes: Any, redis_url: str, outils: Any
) -> None:
    async with _monter(plateforme_commandes, redis_url) as montage:
        jeton_de_b = await montage.admettre(_client("client-b-admis"), montage.plateforme.seance.id)

        reponse = await montage.commander(_client("client-a-intrus"), ["A1"], jeton_de_b)

        outils.exiger_probleme(reponse, 403, "ADMISSION_INVALID", "jeton d'un autre client")
        await _aucune_trace(montage, "client-a-intrus")


@pytest.mark.concurrence
async def test_deux_clients_admis_sur_la_meme_place_n_ont_qu_un_gagnant(
    plateforme_commandes: Any, redis_url: str, outils: Any
) -> None:
    async with _monter(plateforme_commandes, redis_url) as montage:
        clients = [_client("client-admis-1"), _client("client-admis-2")]
        jetons = [await montage.admettre(qui, montage.plateforme.seance.id) for qui in clients]

        async def appel(numero: int) -> httpx.Response:
            return await montage.commander(
                clients[numero],
                ["A1"],
                jetons[numero],
                instance=montage.plateforme.instance(numero),
            )

        reponses = await outils.barriere(2, appel)

        assert sorted(r.status_code for r in reponses) == [201, 409], [r.text for r in reponses]
        perdante = next(r for r in reponses if r.status_code == 409)
        outils.exiger_probleme(perdante, 409, "SEAT_ALREADY_TAKEN", "client admis perdant")
        gagnante = next(r for r in reponses if r.status_code == 201).json()
        assert gagnante["statut"] == "CONFIRMEE"
        paiements = await montage.plateforme.bases.paiements_de()
        assert [str(p["commande_id"]) for p in paiements] == [gagnante["id"]]
