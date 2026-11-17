"""Parcours d'un revendeur partenaire (BIL-012) sur la plateforme locale : isolation et Newman.

Joués contre `make up` puis `make demo` par `make test-smoke`, jamais par la CI. Le revendeur
(`revendeur-test`, Client Credentials) passe par l'hôte des revendeurs (`HOTE_PARTENAIRES`,
`partenaires.localhost` par défaut, chaîne `partenaires@file`), le client direct (`client.test`,
Authorization Code + PKCE comme le front) par l'hôte standard. Secrets et mots de passe lus dans
`.env`, jamais écrits ici. Chaque test est ignoré si la gateway ne répond pas, si un secret manque
ou si le jeu de démonstration n'est pas chargé. Chaque passage fait acheter une place au
revendeur : au-delà du plafond de 10 billets par séance (BIL-008), les tests sont ignorés avec
le message « make reset » plutôt que de signaler une fausse régression.
"""

import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.smoke

GATEWAY = "http://localhost"
RACINE = Path(__file__).resolve().parents[2]
SOIREE_JAZZ = "6b1f0c2e-4d5a-4e8b-9c11-0d0e0b000005"
CARTE_ACCEPTEE = "4242424242424242"
IMAGE_NEWMAN = "postman/newman:6.1.3-alpine"
PLAFOND_ATTEINT = "TICKET_LIMIT_EXCEEDED"
MESSAGE_PLAFOND = "Plafond de 10 billets par séance atteint par revendeur-test : lancer make reset"


def _module_comptes() -> ModuleType:
    """Parcours PKCE de `test_comptes.py`, réutilisé sans le recopier."""
    chemin = Path(__file__).with_name("test_comptes.py")
    spec = importlib.util.spec_from_file_location("smoke_comptes", chemin)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPTES = _module_comptes()


@pytest.fixture(scope="module")
def env() -> dict[str, str]:
    valeurs: dict[str, str] = COMPTES._lire_env()
    return valeurs


@pytest.fixture(scope="module")
def oidc(env: dict[str, str]) -> str:
    try:
        httpx.get(f"{GATEWAY}/", timeout=3.0)
    except httpx.HTTPError:
        pytest.skip(f"La gateway ne répond pas sur {GATEWAY} : lancer make up")
    realm = env.get("KEYCLOAK_REALM") or "billetterie"
    return f"{GATEWAY}/auth/realms/{realm}/protocol/openid-connect"


@pytest.fixture(scope="module")
def hote_partenaires(env: dict[str, str]) -> str:
    return env.get("HOTE_PARTENAIRES") or "partenaires.localhost"


@pytest.fixture(scope="module")
def jeton_revendeur(env: dict[str, str], oidc: str) -> str:
    secret = env.get("KEYCLOAK_REVENDEUR_SECRET")
    if not secret:
        pytest.skip("KEYCLOAK_REVENDEUR_SECRET absent de .env")
    reponse = httpx.post(
        f"{oidc}/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "revendeur-test",
            "client_secret": secret,
        },
        timeout=10.0,
    )
    assert reponse.status_code == 200, f"Keycloak refuse le revendeur ({reponse.status_code})"
    return str(reponse.json()["access_token"])


@pytest.fixture(scope="module")
def jeton_client(env: dict[str, str], oidc: str) -> str:
    mot_de_passe = env.get("KEYCLOAK_MDP_CLIENT")
    if not mot_de_passe:
        pytest.skip("KEYCLOAK_MDP_CLIENT absent de .env")
    return str(COMPTES._jeton_pkce(oidc, "client.test", mot_de_passe))


def _place_libre() -> str:
    reponse = httpx.get(
        f"{GATEWAY}/api/v1/seats",
        params={"seance_id": SOIREE_JAZZ, "size": 100},
        timeout=10.0,
    )
    if reponse.status_code != 200 or reponse.json()["total"] == 0:
        pytest.skip("Séance de démonstration sans places : lancer make demo")
    libres = [p["id"] for p in reponse.json()["elements"] if p["disponible"]]
    if not libres:
        pytest.skip("Aucune place disponible sur la première page de la séance de démonstration")
    return str(libres[0])


def _appel(
    methode: str, chemin: str, jeton: str, hote: str | None = None, **options: Any
) -> httpx.Response:
    en_tetes = {"Authorization": f"Bearer {jeton}"}
    if hote:
        en_tetes["Host"] = hote
    return httpx.request(methode, f"{GATEWAY}{chemin}", headers=en_tetes, timeout=15.0, **options)


def test_un_revendeur_et_un_client_direct_ne_voient_que_leurs_propres_commandes(
    jeton_revendeur: str, jeton_client: str, hote_partenaires: str
) -> None:
    creation = _appel(
        "POST",
        "/api/v1/orders",
        jeton_revendeur,
        hote_partenaires,
        json={
            "seance_id": SOIREE_JAZZ,
            "place_ids": [_place_libre()],
            "carte_test": CARTE_ACCEPTEE,
        },
    )
    if creation.status_code == 409 and creation.json().get("code") == PLAFOND_ATTEINT:
        pytest.skip(MESSAGE_PLAFOND)
    assert creation.status_code == 201, creation.text
    commande = creation.json()["id"]
    assert "canal" not in creation.json()

    siennes = _appel(
        "GET", "/api/v1/orders", jeton_revendeur, hote_partenaires, params={"size": 100}
    )
    assert siennes.status_code == 200, siennes.text
    assert commande in {c["id"] for c in siennes.json()["elements"]}

    # Le client direct, sur l'hôte standard, ne la voit ni dans sa liste ni par son identifiant.
    autres = _appel("GET", "/api/v1/orders", jeton_client, params={"size": 100})
    assert autres.status_code == 200, autres.text
    assert commande not in {c["id"] for c in autres.json()["elements"]}
    detail = _appel("GET", f"/api/v1/orders/{commande}", jeton_client)
    assert detail.status_code == 404, detail.text
    assert detail.json()["code"] == "ORDER_NOT_FOUND"

    # Le jeton du revendeur est refusé sur l'hôte standard : il ne contourne pas son quota.
    standard = _appel("GET", "/api/v1/orders", jeton_revendeur)
    assert standard.status_code == 403, standard.text
    assert standard.json()["code"] == "ROLE_MANQUANT"


def test_la_collection_postman_du_revendeur_passe_dans_newman(
    env: dict[str, str], jeton_revendeur: str, hote_partenaires: str
) -> None:
    _place_libre()
    # Newman tourne sur le réseau de la plateforme : Traefik y répond sous `traefik` et, par
    # son alias réseau, sous l'hôte des revendeurs. Le secret passe par l'environnement.
    commande_newman = (
        'newman run partenaires.json --env-var "client_secret=$SECRET"'
        f" --env-var base_url=http://traefik --env-var base_partenaires=http://{hote_partenaires}"
        " --reporters cli --reporter-cli-no-console"
    )
    resultat = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "billetterie",
            "-v",
            f"{RACINE / 'postman'}:/etc/newman:ro",
            "-e",
            "SECRET",
            "--entrypoint",
            "sh",
            IMAGE_NEWMAN,
            "-c",
            commande_newman,
        ],
        env={**os.environ, "SECRET": env["KEYCLOAK_REVENDEUR_SECRET"], "MSYS_NO_PATHCONV": "1"},
        capture_output=True,
        text=True,
        timeout=180,
    )

    if resultat.returncode != 0 and PLAFOND_ATTEINT in resultat.stdout:
        pytest.skip(MESSAGE_PLAFOND)
    assert resultat.returncode == 0, resultat.stdout[-4000:] + resultat.stderr[-2000:]
