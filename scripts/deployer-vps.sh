#!/usr/bin/env bash
# Déploie (ou redéploie) la démo sur la VM, depuis le poste de développement (BIL-017).
#
#   bash scripts/deployer-vps.sh ubuntu@<ip>          # main, images construites sur la VM
#   bash scripts/deployer-vps.sh ubuntu@<ip> <branche> # une autre branche poussée sur GitHub
#
# Prérequis : scripts/vps-installer.sh puis scripts/vps-env.sh lancés une fois sur la VM ;
# clé SSH chargée dans votre agent (ssh-add). Le script ne lit ni n'envoie aucun secret : le
# .env.prod reste sur la VM. Il tire le code de GitHub, construit les images (ARM) sur la VM,
# relance la plateforme, attend qu'elle soit saine et charge le jeu de démonstration
# (idempotent : un second chargement ne crée aucun doublon).
#
# Chemin manuel tant que GitHub Actions est indisponible ; .github/workflows/deploiement.yml
# fait la même chose avec les images de GHCR une fois le compte débloqué.

set -euo pipefail

HOTE="${1:?usage : bash scripts/deployer-vps.sh <utilisateur>@<ip> [branche]}"
BRANCHE="${2:-main}"
case "$BRANCHE" in
  *[!A-Za-z0-9._/-]*) echo "Nom de branche refusé : $BRANCHE" >&2; exit 1 ;;
esac

# Commandes jouées sur la VM. COMPOSE résume les fichiers et l'environnement de la démo.
ssh "$HOTE" BRANCHE="$BRANCHE" bash -s <<'SUR_LA_VM'
set -euo pipefail
cd /opt/billetterie
[ -f .env.prod ] || { echo ".env.prod absent : lancer d'abord bash scripts/vps-env.sh sur la VM." >&2; exit 1; }
COMPOSE="docker compose -f compose.prod.yaml -f compose.prod.build.yaml --env-file .env.prod"

echo "== Code : $BRANCHE"
git fetch --quiet origin
git checkout --quiet "$BRANCHE"
git pull --quiet --ff-only origin "$BRANCHE"
git log --oneline -1

echo "== Construction des images (ARM, sur la VM)"
$COMPOSE build

echo "== Démarrage (attend que tout soit sain)"
$COMPOSE up -d --wait --remove-orphans

echo "== Jeu de démonstration"
$COMPOSE run --rm --no-deps catalogue-migrations python -m catalogue.demo

echo "== État"
$COMPOSE ps --format '{{.Service}} {{.Status}}'
DOMAINE="$(grep '^DOMAINE=' .env.prod | cut -d= -f2-)"
echo "Démo : https://$DOMAINE"
SUR_LA_VM
