"""BIL-001 : les cinq squelettes dans le compose local, résolu par `docker compose config`.

Le fichier d'environnement est synthétique (conftest : valeurs_env_locale). Les tests à argument
`squelette` sont paramétrés sur la table SERVICES du conftest (nom, paquet, ressource,
instances) ; l'argument est typé Any, le conftest n'étant pas importable en mode importlib.
"""

import re
import subprocess
from collections.abc import Callable
from typing import Any

import pytest

# Bases de la plateforme locale (infra/postgres/init/01-bases.sh).
BASES = {"echo", "keycloak", "catalogue", "billets", "commandes", "paiements", "notifications"}
COMMANDE_MIGRATIONS = ["alembic", "upgrade", "head"]


def _services(config: Any) -> dict[str, Any]:
    services: dict[str, Any] = config.get("services", {})
    return services


def _definition(config: Any, nom: str) -> dict[str, Any]:
    services = _services(config)
    assert nom in services, f"{nom} absent du compose local ({sorted(services)})"
    definition: dict[str, Any] = services[nom]
    return definition


def _environnement(config: Any, nom: str) -> dict[str, str]:
    environnement: dict[str, str] = _definition(config, nom).get("environment") or {}
    return environnement


def _conteneurs(squelette: Any) -> list[str]:
    """Conteneurs d'un service : sa migration, puis ses instances."""
    return [squelette.migrations, *squelette.instances]


def test_la_configuration_locale_est_valide_avec_un_environnement_synthetique(
    compose_local: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> None:
    resultat = compose_local(["--quiet"])

    assert resultat.returncode == 0, resultat.stderr


def test_chaque_service_lit_sa_propre_base_dans_le_compose(
    config_locale: Any, valeurs_env_locale: dict[str, str], squelette: Any
) -> None:
    nom = squelette.nom
    mot_de_passe = valeurs_env_locale[squelette.variable_mot_de_passe]
    attendue = f"postgresql+asyncpg://{nom}:{mot_de_passe}@postgres:5432/{nom}"
    autres_bases = BASES - {nom}

    for conteneur in _conteneurs(squelette):
        environnement = _environnement(config_locale, conteneur)
        assert environnement.get("DATABASE_URL") == attendue, conteneur
        for variable, valeur in environnement.items():
            for autre in autres_bases:
                assert not re.search(rf"@postgres:5432/{autre}\b", str(valeur)), (
                    f"{conteneur} : {variable} vise la base {autre}"
                )


def test_billets_et_commandes_ont_deux_instances_et_les_autres_une(
    config_locale: Any, services_metier: Any
) -> None:
    services = _services(config_locale)

    for squelette in services_metier:
        instances = {nom for nom in services if re.fullmatch(rf"{squelette.nom}-\d+", nom)}
        assert instances == set(squelette.instances), squelette.nom
        for instance in squelette.instances:
            assert _environnement(config_locale, instance).get("INSTANCE") == instance


def test_chaque_service_migre_une_seule_fois_avant_ses_instances(
    config_locale: Any, squelette: Any
) -> None:
    migrations = _definition(config_locale, squelette.migrations)
    image = migrations.get("image")

    assert migrations.get("command") == COMMANDE_MIGRATIONS
    assert migrations.get("depends_on", {}).get("postgres", {}).get("condition") == (
        "service_healthy"
    )
    # Une seule migration par service : aucun autre conteneur de la même image ne migre.
    migrants = [
        nom
        for nom, definition in _services(config_locale).items()
        if definition.get("image") == image and definition.get("command") == COMMANDE_MIGRATIONS
    ]
    assert migrants == [squelette.migrations]

    for instance in squelette.instances:
        definition = _definition(config_locale, instance)
        dependances = definition.get("depends_on", {})
        assert definition.get("image") == image, instance
        assert dependances.get(squelette.migrations, {}).get("condition") == (
            "service_completed_successfully"
        ), instance
        assert dependances.get("consul", {}).get("condition") == "service_healthy", instance


def test_aucun_squelette_ne_publie_de_port_sur_l_hote(
    config_locale: Any, services_metier: Any
) -> None:
    for squelette in services_metier:
        for conteneur in _conteneurs(squelette):
            assert not _definition(config_locale, conteneur).get("ports"), conteneur


# Décisions Q16 et Q18 du plan BIL-004 : catalogue publie par l'outbox, son relais a besoin de
# RabbitMQ ; il n'est plus un squelette vide. BIL-006 (décision Q5) : billets consomme
# ticketing.show.scheduled, il n'en est plus un non plus. BIL-008 (décisions du squelette) :
# commandes publie ticketing.order.confirmed et ticketing.order.expired par l'outbox. BIL-011 :
# paiements consomme ticketing.show.cancelled et ticketing.ticket.rejected, publie
# ticketing.payment.refunded par l'outbox.
@pytest.mark.sauf_services("catalogue", "billets", "commandes", "paiements")
def test_les_squelettes_ne_dependent_pas_de_rabbitmq(config_locale: Any, squelette: Any) -> None:
    for conteneur in _conteneurs(squelette):
        definition = _definition(config_locale, conteneur)
        assert "RABBITMQ_URL" not in (definition.get("environment") or {}), conteneur
        assert "rabbitmq" not in (definition.get("depends_on") or {}), conteneur


# BIL-005 (Q3 du plan) : le catalogue lit son cache dans le Redis de la plateforme.
def test_catalogue_est_configure_avec_redis(config_locale: Any) -> None:
    instance = _definition(config_locale, "catalogue-1")

    assert _environnement(config_locale, "catalogue-1").get("REDIS_URL") == ("redis://redis:6379/0")
    assert (instance.get("depends_on") or {}).get("redis", {}).get("condition") == (
        "service_healthy"
    )


# BIL-006 (décision Q20) : billets pose ses verrous dans le Redis de la plateforme et consomme
# ticketing.show.scheduled sur RabbitMQ ; l'ancre billets-env sert la migration et les instances.
def test_billets_est_configure_avec_redis_et_rabbitmq(
    config_locale: Any, services_metier: Any
) -> None:
    (billets,) = [squelette for squelette in services_metier if squelette.nom == "billets"]

    for conteneur in _conteneurs(billets):
        environnement = _environnement(config_locale, conteneur)
        assert str(environnement.get("REDIS_URL", "")).startswith("redis://redis:6379"), conteneur
        assert "@rabbitmq:5672" in str(environnement.get("RABBITMQ_URL", "")), conteneur
    for instance in billets.instances:
        dependances = _definition(config_locale, instance).get("depends_on") or {}
        assert {"redis", "rabbitmq"} <= set(dependances), (instance, sorted(dependances))


# BIL-008 (décision Q23, décisions du squelette) : commandes appelle Billets, Catalogue et
# Paiements par la gateway avec le jeton du client Keycloak `services`, et relaie son outbox
# sur RabbitMQ ; ancre commandes-env.
def test_commandes_est_configure_avec_la_gateway_keycloak_et_rabbitmq(
    config_locale: Any, services_metier: Any, valeurs_env_locale: dict[str, str]
) -> None:
    (commandes,) = [squelette for squelette in services_metier if squelette.nom == "commandes"]
    realm = valeurs_env_locale["KEYCLOAK_REALM"]

    for instance in commandes.instances:
        environnement = _environnement(config_locale, instance)
        assert (
            environnement.get("SERVICES_CLIENT_SECRET")
            == (valeurs_env_locale["KEYCLOAK_SERVICES_SECRET"])
        ), instance
        assert environnement.get("URL_GATEWAY") == "http://traefik", instance
        assert environnement.get("URL_JETON") == (
            f"http://keycloak:8080/auth/realms/{realm}/protocol/openid-connect/token"
        ), instance
        assert "@rabbitmq:5672" in str(environnement.get("RABBITMQ_URL", "")), instance
        dependances = _definition(config_locale, instance).get("depends_on") or {}
        assert "rabbitmq" in dependances, (instance, sorted(dependances))
