"""Places d'une séance (BIL-006) : disponibilité publique et verrou, sur la plateforme locale.

Joués contre `make up` puis `make demo` par `make test-smoke`, jamais par la CI. La séance
« Soirée jazz » du jeu de démonstration (identifiant fixe) a 70 places, créées par billets à la
réception de `ticketing.show.scheduled` : sa disponibilité prouve la chaîne catalogue, outbox,
RabbitMQ, billets. Le jeton du client `services` est demandé à Keycloak avec le secret lu dans
`.env`, jamais écrit ici. Chaque test est ignoré si la gateway ne répond pas, si le jeu de
démonstration n'est pas chargé ou si son secret manque. Le verrou posé n'est levé par aucune
route (décision Q2) : la place reste prise 10 min, le test prend la première place disponible.
"""

import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.smoke

GATEWAY = "http://localhost"
RACINE = Path(__file__).resolve().parents[2]
SOIREE_JAZZ = "6b1f0c2e-4d5a-4e8b-9c11-0d0e0b000005"


def _lire_env() -> dict[str, str]:
    fichier = RACINE / ".env"
    if not fichier.exists():
        return {}
    valeurs: dict[str, str] = {}
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        nom, valeur = ligne.split("=", 1)
        valeurs[nom.strip()] = valeur.strip().strip("'\"")
    return valeurs


def _places(seance: str, page: int = 1) -> httpx.Response:
    return httpx.get(
        f"{GATEWAY}/api/v1/seats",
        params={"seance_id": seance, "page": page, "size": 100},
        timeout=10.0,
    )


@pytest.fixture(scope="module")
def gateway() -> str:
    try:
        httpx.get(f"{GATEWAY}/", timeout=3.0)
    except httpx.HTTPError:
        pytest.skip(f"La gateway ne répond pas sur {GATEWAY} : lancer make up")
    return GATEWAY


@pytest.fixture(scope="module")
def places_demo(gateway: str) -> list[dict[str, Any]]:
    reponse = _places(SOIREE_JAZZ)
    if reponse.status_code != 200 or reponse.json()["total"] == 0:
        pytest.skip("Séance de démonstration sans places : lancer make demo")
    return list(reponse.json()["elements"])


@pytest.fixture(scope="module")
def jeton_services(gateway: str) -> str:
    env = _lire_env()
    secret = env.get("KEYCLOAK_SERVICES_SECRET")
    if not secret:
        pytest.skip("KEYCLOAK_SERVICES_SECRET absent de .env")
    realm = env.get("KEYCLOAK_REALM") or "billetterie"
    reponse = httpx.post(
        f"{gateway}/auth/realms/{realm}/protocol/openid-connect/token",
        data={"grant_type": "client_credentials", "client_id": "services", "client_secret": secret},
        timeout=10.0,
    )
    assert reponse.status_code == 200, "Keycloak refuse le client services"
    return str(reponse.json()["access_token"])


def test_la_disponibilite_d_une_seance_de_demonstration_repond_sans_jeton(
    places_demo: list[dict[str, Any]],
) -> None:
    reponse = _places(SOIREE_JAZZ)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert set(corps) == {"elements", "page", "size", "total"}
    assert corps["total"] == 70
    assert set(corps["elements"][0]) == {
        "id",
        "seance_id",
        "rang",
        "numero",
        "categorie_id",
        "disponible",
    }
    assert reponse.headers.get("x-correlation-id")


def test_sans_jeton_le_verrouillage_est_refuse_via_traefik(gateway: str) -> None:
    reponse = httpx.put(
        f"{gateway}/api/v1/seats/{uuid.uuid4()}/lock",
        json={"seance_id": SOIREE_JAZZ, "commande_id": str(uuid.uuid4())},
        timeout=10.0,
    )

    assert reponse.status_code == 401, reponse.text
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert reponse.headers.get("www-authenticate", "").startswith("Bearer")


def test_le_client_services_verrouille_une_place_puis_une_autre_commande_est_refusee(
    places_demo: list[dict[str, Any]], jeton_services: str
) -> None:
    libres = [place for place in places_demo if place["disponible"]]
    if not libres:
        pytest.skip("Aucune place disponible sur la première page : rejouer après 10 min")
    place = libres[0]["id"]
    en_tetes = {"Authorization": f"Bearer {jeton_services}"}

    def verrouiller(commande: str) -> httpx.Response:
        return httpx.put(
            f"{GATEWAY}/api/v1/seats/{place}/lock",
            json={"seance_id": SOIREE_JAZZ, "commande_id": commande},
            headers=en_tetes,
            timeout=10.0,
        )

    premiere = verrouiller(str(uuid.uuid4()))
    assert premiere.status_code == 200, premiere.text

    seconde = verrouiller(str(uuid.uuid4()))
    assert seconde.status_code == 409, seconde.text
    assert seconde.json()["code"] == "SEAT_ALREADY_TAKEN"

    apres = {p["id"]: p["disponible"] for p in _places(SOIREE_JAZZ).json()["elements"]}
    assert apres[place] is False
