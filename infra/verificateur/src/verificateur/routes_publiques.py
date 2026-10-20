"""Routes accessibles sans jeton, configurées par la variable ROUTES_PUBLIQUES.

Format : « MÉTHODE /préfixe » séparés par des virgules, par exemple
`GET /api/v1/evenements,GET /api/v1/seances`. Un préfixe couvre ses sous-chemins segment par
segment : `/api/v1/evenements` couvre `/api/v1/evenements/42`, pas `/api/v1/evenementsX`.
"""

import posixpath
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class RoutePublique:
    methode: str
    prefixe: str

    def couvre(self, methode: str, chemin: str) -> bool:
        if methode != self.methode:
            return False
        return chemin == self.prefixe or chemin.startswith(f"{self.prefixe}/")


def analyser(texte: str) -> tuple[RoutePublique, ...]:
    """Lit la variable ; une entrée mal formée arrête le démarrage plutôt que d'être ignorée."""
    routes = []
    for entree in texte.split(","):
        if not entree.strip():
            continue
        parties = entree.split()
        if len(parties) != 2 or not parties[1].startswith("/"):
            raise ValueError(f"Route publique mal formée : {entree.strip()!r}")
        methode, prefixe = parties
        routes.append(RoutePublique(methode.upper(), prefixe.rstrip("/") or "/"))
    return tuple(routes)


def chemin_normalise(uri: str) -> str:
    """Chemin de l'URI d'origine, sans requête ni `..` : `/a/../b` ne doit pas passer pour `/a`."""
    chemin = posixpath.normpath(unquote(urlsplit(uri).path) or "/")
    # normpath garde un double slash initial (« //a ») : on le ramène à un seul.
    return "/" + chemin.lstrip("/")


def est_publique(routes: tuple[RoutePublique, ...], methode: str, uri: str) -> bool:
    chemin = chemin_normalise(uri)
    return any(route.couvre(methode.upper(), chemin) for route in routes)
