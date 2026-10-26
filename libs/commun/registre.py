"""Inscription des instances de service dans le registre Consul.

Au démarrage, une instance s'enregistre avec un check HTTP sur `/health` ; Consul la retire
d'elle-même si elle reste critique plus d'une minute (arrêt brutal, plantage). À l'arrêt
normal, elle se désenregistre. L'adresse de Consul vient uniquement de `CONSUL_URL`.

Les tags portent la route Traefik du service (voir `tags_traefik`) : aucune route n'est écrite
dans la configuration de la gateway.

Utilisation dans un service :

    app = FastAPI(
        lifespan=lifespan_registre(
            "billets", adresse="billets-1", port=8000, tags=tags_traefik("billets", "seats")
        )
    )
"""

import logging
import os
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
from fastapi import FastAPI

journal = logging.getLogger(__name__)

INTERVALLE_CHECK = "10s"
DELAI_CHECK = "5s"
RETRAIT_APRES_CRITIQUE = "1m"
DELAI_APPEL_CONSUL = 5.0

# Point d'entrée Traefik des routes : `web` en local (HTTP), `websecure` en démo (HTTPS).
VARIABLE_POINT_ENTREE = "TRAEFIK_POINT_ENTREE"
POINT_ENTREE_PAR_DEFAUT = "web"

# Priorité du routeur de santé (tags_sante_traefik) : bien au-dessus de la longueur de toute
# règle PathPrefix (priorité implicite chez Traefik). Sa règle Path(...) ne vise qu'un chemin
# exact : elle ne peut capter aucune autre route.
PRIORITE_ROUTEUR_SANTE = 1000


def _client_consul() -> httpx.AsyncClient:
    url = os.environ.get("CONSUL_URL")
    if not url:
        raise RuntimeError("La variable d'environnement CONSUL_URL n'est pas définie.")
    return httpx.AsyncClient(base_url=url, timeout=DELAI_APPEL_CONSUL)


def identifiant_instance(nom: str, adresse: str, port: int) -> str:
    """Identifiant unique d'une instance : distingue les instances d'un même service."""
    return f"{nom}-{adresse}-{port}"


def tags_traefik(
    nom: str,
    *ressources: str,
    middlewares: str = "standard@file",
    point_entree: str | None = None,
) -> list[str]:
    """Tags Consul qui exposent le service derrière Traefik.

    Chaque ressource devient une règle `PathPrefix(/api/v1/<ressource>)`. Les middlewares sont
    une chaîne définie dans infra/traefik/dynamique.yml : `standard@file` pour le front et les
    clients, `partenaires@file` pour l'API des revendeurs.

    `point_entree` : point d'entrée Traefik du routeur. None : valeur de la variable
    d'environnement `VARIABLE_POINT_ENTREE`, `web` si elle est absente (local).
    """
    entree = point_entree or os.environ.get(VARIABLE_POINT_ENTREE) or POINT_ENTREE_PAR_DEFAUT
    if not ressources:
        raise ValueError("Au moins une ressource est nécessaire pour router le service.")
    regle = " || ".join(f"PathPrefix(`/api/v1/{ressource}`)" for ressource in ressources)
    routeur = f"traefik.http.routers.{nom}"
    return [
        "traefik.enable=true",
        f"{routeur}.rule={regle}",
        f"{routeur}.entrypoints={entree}",
        f"{routeur}.middlewares={middlewares}",
    ]


def tags_sante_traefik(
    nom: str,
    ressource: str,
    middlewares: str = "standard@file",
    point_entree: str | None = None,
) -> list[str]:
    """Tags Consul d'un second routeur qui expose `/health` sous le préfixe du service.

    `GET /api/v1/<ressource>/health` est réécrit en `/health` (middleware `replacePath` déclaré
    dans ces mêmes tags) après la chaîne `middlewares` (jeton requis avec `standard@file`).
    Priorité explicite (`PRIORITE_ROUTEUR_SANTE`) : le routeur passe avant le `PathPrefix(...)`
    de `tags_traefik`, dont la priorité implicite est la longueur de sa règle.

    À ajouter aux tags de `tags_traefik` : `traefik.enable=true` n'est pas répété.
    """
    if not ressource:
        raise ValueError("Une ressource est nécessaire pour router la santé du service.")
    entree = point_entree or os.environ.get(VARIABLE_POINT_ENTREE) or POINT_ENTREE_PAR_DEFAUT
    nom_sante = f"{nom}-sante"
    routeur = f"traefik.http.routers.{nom_sante}"
    return [
        # GET seul : la route /health du service n'accepte pas d'autre méthode.
        f"{routeur}.rule=Path(`/api/v1/{ressource}/health`) && Method(`GET`)",
        f"{routeur}.priority={PRIORITE_ROUTEUR_SANTE}",
        f"{routeur}.entrypoints={entree}",
        f"{routeur}.middlewares={middlewares},{nom_sante}",
        f"traefik.http.middlewares.{nom_sante}.replacepath.path=/health",
    ]


async def enregistrer(
    nom: str,
    adresse: str,
    port: int,
    tags: Sequence[str] = (),
    chemin_sante: str = "/health",
    chemin_metriques: str | None = "/metrics",
) -> str:
    """Enregistre l'instance dans Consul et renvoie son identifiant.

    `chemin_metriques` est annoncé dans les métadonnées (`metriques`) : Prometheus mesure toute
    instance qui le porte (infra/prometheus/prometheus.yml). None : instance non mesurée.

    Lève une erreur si Consul refuse ou ne répond pas : une instance absente du registre ne
    recevrait aucun trafic, elle ne doit donc pas démarrer.
    """
    identifiant = identifiant_instance(nom, adresse, port)
    definition = {
        "ID": identifiant,
        "Name": nom,
        "Address": adresse,
        "Port": port,
        "Tags": list(tags),
        "Meta": {"metriques": chemin_metriques} if chemin_metriques else {},
        "Check": {
            # Routée dès l'inscription : sans cela, une instance réinscrite (redémarrage de
            # Consul) resterait « critical », donc hors de Traefik, jusqu'à son premier check.
            # L'inscription a lieu en fin de démarrage, quand l'instance est prête.
            "Status": "passing",
            "HTTP": f"http://{adresse}:{port}{chemin_sante}",
            "Interval": INTERVALLE_CHECK,
            "Timeout": DELAI_CHECK,
            "DeregisterCriticalServiceAfter": RETRAIT_APRES_CRITIQUE,
        },
    }
    async with _client_consul() as client:
        reponse = await client.put("/v1/agent/service/register", json=definition)
        reponse.raise_for_status()
    journal.info("Instance %s enregistrée dans Consul", identifiant)
    return identifiant


async def desenregistrer(identifiant: str) -> None:
    """Retire l'instance du registre.

    Un échec est seulement journalisé : l'arrêt du service ne doit pas être bloqué, et
    Consul retirera de toute façon l'instance une fois son check critique.
    """
    try:
        async with _client_consul() as client:
            reponse = await client.put(f"/v1/agent/service/deregister/{identifiant}")
            reponse.raise_for_status()
    except httpx.HTTPError:
        journal.warning("Désenregistrement de %s impossible", identifiant, exc_info=True)
        return
    journal.info("Instance %s désenregistrée de Consul", identifiant)


@asynccontextmanager
async def inscription(
    nom: str,
    adresse: str,
    port: int,
    tags: Sequence[str] = (),
    chemin_sante: str = "/health",
) -> AsyncIterator[str]:
    """Enregistre l'instance à l'entrée du bloc et la désenregistre à la sortie."""
    identifiant = await enregistrer(nom, adresse, port, tags, chemin_sante)
    try:
        yield identifiant
    finally:
        await desenregistrer(identifiant)


def lifespan_registre(
    nom: str,
    adresse: str,
    port: int,
    tags: Sequence[str] = (),
    chemin_sante: str = "/health",
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Lifespan FastAPI qui inscrit l'instance au démarrage et la retire à l'arrêt."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with inscription(nom, adresse, port, tags, chemin_sante):
            yield

    return lifespan
