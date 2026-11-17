"""Comptes clients de charge pour k6 : création locale et jetons d'accès (BIL-015, suivi).

Un seul jeton partagé par tous les utilisateurs virtuels fausse la mesure : la file d'attente
voit un seul client. Ce script crée `charge-001` à `charge-<N>` (rôle customer) dans le realm
de la plateforme LOCALE, par l'API d'administration de Keycloak, avec un mot de passe aléatoire
tiré à chaque exécution et jamais écrit ni affiché ; puis il connecte chaque compte comme le
front (Authorization Code + PKCE, client `frontend`) et écrit les jetons, un par ligne, dans
`infra/charge/jetons.txt` (ignoré par git), lu par k6 via `JETONS_FICHIER`.

Le realm versionné n'est pas modifié : ces comptes n'existent que dans la base Keycloak locale
et disparaissent avec `--supprimer` ou `make reset`. Refusé sur une autre adresse que localhost
(l'API d'administration n'est de toute façon pas routée sur la démo).

Usage (plateforme démarrée, `.env` rempli) :
    uv run python infra/charge/comptes.py --nombre 200
    uv run python infra/charge/comptes.py --supprimer

Un jeton vit 5 minutes (accessTokenLifespan du realm) : lancer k6 juste après.
"""

import argparse
import base64
import hashlib
import html
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

RACINE = Path(__file__).resolve().parents[2]
FICHIER_JETONS = Path(__file__).resolve().parent / "jetons.txt"
PREFIXE = "charge-"
DELAI = 15.0


def lire_env() -> dict[str, str]:
    """Valeurs du `.env` racine, sans jamais les afficher."""
    fichier = RACINE / ".env"
    if not fichier.exists():
        sys.exit(".env introuvable à la racine du dépôt.")
    valeurs: dict[str, str] = {}
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            valeurs[cle.strip()] = valeur.strip().strip('"').strip("'")
    return valeurs


def exiger(env: dict[str, str], nom: str) -> str:
    valeur = env.get(nom, "")
    if not valeur:
        sys.exit(f"Variable {nom} absente du .env.")
    return valeur


class AdminKeycloak:
    """Appels à l'API d'administration avec un jeton du realm master (client admin-cli)."""

    def __init__(self, base: str, realm: str, utilisateur: str, mot_de_passe: str) -> None:
        self._client = httpx.Client(base_url=f"{base}/auth", timeout=DELAI)
        reponse = self._client.post(
            "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": utilisateur,
                "password": mot_de_passe,
            },
        )
        if reponse.status_code != 200:
            sys.exit(f"Connexion administrateur refusée ({reponse.status_code}).")
        self._client.headers["Authorization"] = f"Bearer {reponse.json()['access_token']}"
        self._realm = f"/admin/realms/{realm}"

    def fermer(self) -> None:
        self._client.close()

    def comptes_de_charge(self) -> list[dict[str, str]]:
        reponse = self._client.get(
            f"{self._realm}/users", params={"search": PREFIXE, "max": 10_000}
        )
        reponse.raise_for_status()
        return [u for u in reponse.json() if str(u.get("username", "")).startswith(PREFIXE)]

    def creer_ou_reinitialiser(self, nom: str, mot_de_passe: str, role: dict[str, str]) -> None:
        identifiant = self._identifiant(nom)
        if identifiant is None:
            reponse = self._client.post(
                f"{self._realm}/users",
                json={
                    "username": nom,
                    "email": f"{nom}@exemple.test",
                    "emailVerified": True,
                    "enabled": True,
                    "firstName": "Charge",
                    "lastName": nom.removeprefix(PREFIXE),
                },
            )
            reponse.raise_for_status()
            identifiant = self._identifiant(nom)
            assert identifiant is not None, nom
            self._client.post(
                f"{self._realm}/users/{identifiant}/role-mappings/realm", json=[role]
            ).raise_for_status()
        self._client.put(
            f"{self._realm}/users/{identifiant}/reset-password",
            json={"type": "password", "value": mot_de_passe, "temporary": False},
        ).raise_for_status()

    def role(self, nom: str) -> dict[str, str]:
        reponse = self._client.get(f"{self._realm}/roles/{nom}")
        reponse.raise_for_status()
        donnees = reponse.json()
        return {"id": donnees["id"], "name": donnees["name"]}

    def supprimer(self, identifiant: str) -> None:
        self._client.delete(f"{self._realm}/users/{identifiant}").raise_for_status()

    def _identifiant(self, nom: str) -> str | None:
        reponse = self._client.get(f"{self._realm}/users", params={"username": nom, "exact": True})
        reponse.raise_for_status()
        trouves = reponse.json()
        return str(trouves[0]["id"]) if trouves else None


def jeton_pkce(base: str, realm: str, utilisateur: str, mot_de_passe: str) -> str:
    """Connexion du front (même parcours que tests/smoke/test_comptes.py)."""
    oidc = f"{base}/auth/realms/{realm}/protocol/openid-connect"
    redirection = f"{base}/rappel"
    verificateur = secrets.token_urlsafe(48)
    defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).rstrip(b"=")
    with httpx.Client(timeout=DELAI) as client:
        page = client.get(
            f"{oidc}/auth",
            params={
                "client_id": "frontend",
                "response_type": "code",
                "redirect_uri": redirection,
                "scope": "openid",
                "state": secrets.token_urlsafe(8),
                "code_challenge": defi.decode(),
                "code_challenge_method": "S256",
            },
        )
        action = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text)
        if action is None:
            sys.exit(f"Formulaire de connexion introuvable ({page.status_code}).")
        # Cookies Keycloak marqués Secure : httpx ne les renvoie pas en HTTP, on les recopie.
        cookies = "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)
        retour = client.post(
            html.unescape(action.group(1)),
            data={"username": utilisateur, "password": mot_de_passe, "credentialId": ""},
            headers={"Cookie": cookies},
        )
        if retour.status_code != 302:
            sys.exit(f"{utilisateur} : connexion refusée ({retour.status_code}).")
        code = parse_qs(urlparse(retour.headers["location"]).query)["code"][0]
        jeton = client.post(
            f"{oidc}/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "frontend",
                "code": code,
                "redirect_uri": redirection,
                "code_verifier": verificateur,
            },
        )
    if jeton.status_code != 200:
        sys.exit(f"{utilisateur} : échange du code refusé ({jeton.status_code}).")
    return str(jeton.json()["access_token"])


def main() -> None:
    arguments = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    arguments.add_argument("--nombre", type=int, default=50, help="comptes à préparer (1-1000)")
    arguments.add_argument("--base", default="http://localhost", help="gateway locale")
    arguments.add_argument("--supprimer", action="store_true", help="supprimer les comptes")
    options = arguments.parse_args()
    if urlparse(options.base).hostname not in {"localhost", "127.0.0.1"}:
        sys.exit("Plateforme locale uniquement (--base sur localhost).")
    if not 1 <= options.nombre <= 1000:
        sys.exit("--nombre entre 1 et 1000.")

    env = lire_env()
    realm = env.get("KEYCLOAK_REALM") or "billetterie"
    admin = AdminKeycloak(
        options.base, realm, exiger(env, "KEYCLOAK_ADMIN"), exiger(env, "KEYCLOAK_ADMIN_PASSWORD")
    )
    try:
        if options.supprimer:
            comptes = admin.comptes_de_charge()
            for compte in comptes:
                admin.supprimer(compte["id"])
            FICHIER_JETONS.unlink(missing_ok=True)
            print(f"{len(comptes)} compte(s) de charge supprimé(s).")
            return

        # Mot de passe commun à la série, tiré à chaque exécution, gardé en mémoire seulement.
        mot_de_passe = secrets.token_urlsafe(24)
        role = admin.role("customer")
        noms = [f"{PREFIXE}{numero:03d}" for numero in range(1, options.nombre + 1)]
        for nom in noms:
            admin.creer_ou_reinitialiser(nom, mot_de_passe, role)
    finally:
        admin.fermer()

    jetons = [jeton_pkce(options.base, realm, nom, mot_de_passe) for nom in noms]
    FICHIER_JETONS.write_text("\n".join(jetons) + "\n", encoding="utf-8")
    print(f"{len(jetons)} jeton(s) écrits dans {FICHIER_JETONS.relative_to(RACINE)} (5 minutes).")


if __name__ == "__main__":
    main()
