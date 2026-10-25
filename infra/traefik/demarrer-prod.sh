#!/bin/sh
# Démarrage de Traefik en démo (compose.prod.yaml).
# Traefik n'interpole pas l'environnement dans sa configuration statique : ce script remplace
# ${DOMAINE}, ${ACME_EMAIL} et ${ACME_CA_SERVER} de traefik.prod.yml, écrit le résultat à
# l'emplacement par défaut (/etc/traefik/traefik.yml, lu aussi par `traefik healthcheck`), puis
# lance Traefik.
set -eu

: "${DOMAINE:=}"
# Nom de domaine en minuscules seulement ([a-z0-9.-]) : rien d'autre n'entre dans la
# configuration, ni dans la commande sed ci-dessous.
case "$DOMAINE" in
  # Liste explicite : un intervalle a-z dépend de la locale (majuscules comprises parfois).
  "" | *[!abcdefghijklmnopqrstuvwxyz0123456789.-]*)
    printf 'DOMAINE invalide : attendu un nom de domaine en minuscules ([a-z0-9.-]), non vide.\n' >&2
    exit 1
    ;;
esac
: "${ACME_EMAIL:?ACME_EMAIL manquant}"
: "${ACME_CA_SERVER:?ACME_CA_SERVER manquant}"

# Les valeurs sont échappées pour sed (\, | et &).
echapper() {
  printf '%s' "$1" | sed -e 's/[\\|&]/\\&/g'
}

sed \
  -e "s|\${DOMAINE}|$(echapper "$DOMAINE")|g" \
  -e "s|\${ACME_EMAIL}|$(echapper "$ACME_EMAIL")|g" \
  -e "s|\${ACME_CA_SERVER}|$(echapper "$ACME_CA_SERVER")|g" \
  /etc/traefik/traefik.prod.yml > /etc/traefik/traefik.yml

exec traefik --configFile=/etc/traefik/traefik.yml
