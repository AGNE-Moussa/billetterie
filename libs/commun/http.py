"""Le seul client HTTP autorisé entre services : timeout, nouvelles tentatives, disjoncteur.

- Timeout de 2 s par défaut sur chaque tentative.
- Nouvelles tentatives (3 tentatives au maximum, backoff exponentiel avec gigue) uniquement sur
  un GET ou une requête portant une clé d'idempotence : un POST sans clé n'est jamais rejoué.
- Un disjoncteur par service cible, partagé par tous les clients du processus : ouvert après
  5 échecs consécutifs (chaque tentative compte), un appel d'essai après 30 s, refermé si
  l'essai réussit. Son état est publié dans la jauge Prometheus client_http_disjoncteur_etat.
- `X-Correlation-Id` de la requête en cours et jeton de service (Client Credentials) ajoutés
  automatiquement.
- Une cible en panne lève `ServiceIndisponible`, renvoyée au client en Problem Details 503.

Les autres services sont joints par la gateway (aucun code de découverte dans les services) :

    async with ClientService("catalogue", "http://traefik", jeton=jeton_service) as catalogue:
        reponse = await catalogue.get("/api/v1/seances/42")
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from enum import IntEnum
from types import TracebackType
from typing import Any, Self

import httpx
from prometheus_client import Gauge
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_random_exponential

from commun.correlation import ENTETE, correlation_id
from commun.erreurs import ErreurMetier

journal = logging.getLogger(__name__)

TIMEOUT_DEFAUT = 2.0
TENTATIVES_MAX = 3
SEUIL_OUVERTURE = 5
DELAI_DEMI_OUVERTURE = 30.0
# Backoff « full jitter » : attente aléatoire entre 0 et min(1 s, 0,1 s x 2^n).
ATTENTE_BASE = 0.1
ATTENTE_MAX = 1.0
# Le jeton est renouvelé un peu avant son expiration, pour ne pas partir périmé.
MARGE_JETON = 30.0

ENTETE_IDEMPOTENCE = "Idempotency-Key"
# Réponses qui signalent une cible en difficulté. Une 4xx vient de l'appelant : ce n'est pas
# un échec de la cible, elle est rendue telle quelle.
STATUTS_ECHEC = frozenset({500, 502, 503, 504})

ETAT_DISJONCTEUR = Gauge(
    "client_http_disjoncteur_etat",
    "État du disjoncteur vers un service cible : 0 fermé, 1 demi-ouvert, 2 ouvert.",
    ["cible"],
)


class ServiceIndisponible(ErreurMetier):
    """La cible ne répond pas, ou son disjoncteur est ouvert."""

    def __init__(self, cible: str) -> None:
        super().__init__(
            "SERVICE_INDISPONIBLE",
            503,
            f"Le service {cible} est momentanément indisponible.",
            titre="Service indisponible",
        )
        self.cible = cible


class Etat(IntEnum):
    FERME = 0
    DEMI_OUVERT = 1
    OUVERT = 2


class Disjoncteur:
    """Disjoncteur d'une cible (pattern Circuit Breaker).

    Fermé : tout passe, les échecs consécutifs sont comptés. Ouvert : tout est refusé sans
    réseau. Demi-ouvert (après `delai` secondes) : un seul appel d'essai passe ; son succès
    referme le disjoncteur, son échec le rouvre pour `delai` secondes.
    """

    def __init__(
        self,
        cible: str,
        seuil: int = SEUIL_OUVERTURE,
        delai: float = DELAI_DEMI_OUVERTURE,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cible = cible
        self._seuil = seuil
        self._delai = delai
        self._horloge = horloge
        self._echecs = 0
        self._ouvert_le = 0.0
        self._essai_en_cours = False
        self._etat = Etat.FERME
        ETAT_DISJONCTEUR.labels(cible=cible).set(Etat.FERME)

    @property
    def etat(self) -> Etat:
        if self._etat is Etat.OUVERT and self._horloge() - self._ouvert_le >= self._delai:
            self._changer(Etat.DEMI_OUVERT)
        return self._etat

    def autoriser(self) -> bool:
        """Réserve le passage d'une tentative ; False si elle doit échouer sans réseau."""
        etat = self.etat
        if etat is Etat.FERME:
            return True
        if etat is Etat.DEMI_OUVERT and not self._essai_en_cours:
            self._essai_en_cours = True
            return True
        return False

    def succes(self) -> None:
        self._essai_en_cours = False
        self._echecs = 0
        if self._etat is not Etat.FERME:
            self._changer(Etat.FERME)

    def echec(self) -> None:
        self._essai_en_cours = False
        self._echecs += 1
        if self._etat is Etat.DEMI_OUVERT or self._echecs >= self._seuil:
            self._ouvert_le = self._horloge()
            self._changer(Etat.OUVERT)

    def abandon(self) -> None:
        """Tentative interrompue (annulation) : ni succès ni échec, l'essai est libéré."""
        self._essai_en_cours = False

    def _changer(self, etat: Etat) -> None:
        if etat is not self._etat:
            journal.warning("Disjoncteur vers %s : %s", self.cible, etat.name.lower())
        self._etat = etat
        ETAT_DISJONCTEUR.labels(cible=self.cible).set(etat)


_disjoncteurs: dict[str, Disjoncteur] = {}


def disjoncteur(cible: str) -> Disjoncteur:
    """Disjoncteur partagé d'une cible : tous les clients du processus voient le même état."""
    if cible not in _disjoncteurs:
        _disjoncteurs[cible] = Disjoncteur(cible)
    return _disjoncteurs[cible]


class JetonService:
    """Jeton du client Keycloak `services` (Client Credentials), gardé jusqu'à son expiration."""

    def __init__(
        self,
        url_jeton: str,
        client_id: str,
        secret: str,
        transport: httpx.AsyncBaseTransport | None = None,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url_jeton
        self._identifiants = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
        }
        self._client = httpx.AsyncClient(timeout=TIMEOUT_DEFAUT, transport=transport)
        self._horloge = horloge
        self._jeton: str | None = None
        self._expire_le = 0.0
        self._verrou = asyncio.Lock()

    async def jeton(self) -> str:
        async with self._verrou:
            if self._jeton is None or self._horloge() >= self._expire_le:
                await self._renouveler()
            assert self._jeton is not None
            return self._jeton

    async def _renouveler(self) -> None:
        try:
            reponse = await self._client.post(self._url, data=self._identifiants)
            reponse.raise_for_status()
            contenu = reponse.json()
            self._jeton = str(contenu["access_token"])
            duree = float(contenu.get("expires_in", 60))
        except (httpx.HTTPError, ValueError, KeyError) as erreur:
            journal.warning("Jeton de service impossible à obtenir", exc_info=True)
            raise ServiceIndisponible("keycloak") from erreur
        self._expire_le = self._horloge() + max(duree - MARGE_JETON, 0.0)

    async def aclose(self) -> None:
        await self._client.aclose()


class _EchecTransitoire(Exception):
    """Tentative échouée côté cible (réseau, timeout, 5xx) : rejouable si l'appel l'est."""


class ClientService:
    def __init__(
        self,
        cible: str,
        base_url: str,
        *,
        jeton: JetonService | None = None,
        timeout: float = TIMEOUT_DEFAUT,
        tentatives_max: int = TENTATIVES_MAX,
        transport: httpx.AsyncBaseTransport | None = None,
        attente: Callable[[float], Awaitable[None]] = asyncio.sleep,
        disjoncteur_cible: Disjoncteur | None = None,
    ) -> None:
        self.cible = cible
        self._jeton = jeton
        self._tentatives_max = tentatives_max
        self._attente = attente
        self._disjoncteur = disjoncteur_cible or disjoncteur(cible)
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def requete(
        self,
        methode: str,
        url: str,
        *,
        cle_idempotence: str | None = None,
        headers: dict[str, str] | None = None,
        **options: Any,
    ) -> httpx.Response:
        """Envoie la requête ; lève ServiceIndisponible si la cible est en panne."""
        methode = methode.upper()
        entetes = dict(headers or {})
        if identifiant := correlation_id():
            entetes[ENTETE] = identifiant
        if cle_idempotence:
            entetes[ENTETE_IDEMPOTENCE] = cle_idempotence
        if self._jeton is not None:
            entetes["Authorization"] = f"Bearer {await self._jeton.jeton()}"

        async def tentative() -> httpx.Response:
            return await self._tentative(methode, url, entetes, options)

        rejouable = methode == "GET" or cle_idempotence is not None
        essais = AsyncRetrying(
            stop=stop_after_attempt(self._tentatives_max if rejouable else 1),
            wait=wait_random_exponential(multiplier=ATTENTE_BASE, max=ATTENTE_MAX),
            # ServiceIndisponible (disjoncteur ouvert) n'est jamais rejouée.
            retry=retry_if_exception_type(_EchecTransitoire),
            sleep=self._attente,
            reraise=True,
        )
        try:
            return await essais(tentative)
        except _EchecTransitoire as erreur:
            raise ServiceIndisponible(self.cible) from erreur

    async def _tentative(
        self, methode: str, url: str, entetes: dict[str, str], options: dict[str, Any]
    ) -> httpx.Response:
        if not self._disjoncteur.autoriser():
            raise ServiceIndisponible(self.cible)
        try:
            reponse = await self._client.request(methode, url, headers=entetes, **options)
        except httpx.TransportError as erreur:  # connexion refusée, timeout, coupure
            self._disjoncteur.echec()
            raise _EchecTransitoire(f"{methode} {url} : {erreur!r}") from erreur
        except BaseException:
            self._disjoncteur.abandon()
            raise
        if reponse.status_code in STATUTS_ECHEC:
            self._disjoncteur.echec()
            raise _EchecTransitoire(f"{methode} {url} : {reponse.status_code}")
        self._disjoncteur.succes()
        return reponse

    async def get(self, url: str, **options: Any) -> httpx.Response:
        return await self.requete("GET", url, **options)

    async def post(self, url: str, **options: Any) -> httpx.Response:
        return await self.requete("POST", url, **options)

    async def put(self, url: str, **options: Any) -> httpx.Response:
        return await self.requete("PUT", url, **options)

    async def patch(self, url: str, **options: Any) -> httpx.Response:
        return await self.requete("PATCH", url, **options)

    async def delete(self, url: str, **options: Any) -> httpx.Response:
        return await self.requete("DELETE", url, **options)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        _type: type[BaseException] | None,
        _erreur: BaseException | None,
        _trace: TracebackType | None,
    ) -> None:
        await self.aclose()
