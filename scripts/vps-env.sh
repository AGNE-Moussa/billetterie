#!/usr/bin/env bash
# Écrit /opt/billetterie/.env.prod sur la VM de démo (BIL-017). À lancer UNE fois, sur la VM.
#
#   cd /opt/billetterie && bash scripts/vps-env.sh
#
# Les mots de passe et clés internes sont tirés au hasard (openssl) et ne quittent jamais la
# VM. Le script demande seulement ce qui vient de vous : adresse IP publique, e-mail de
# Let's Encrypt et identifiants SMTP de Brevo (saisie masquée). Rien n'est affiché ni
# journalisé. Pour recommencer : supprimer .env.prod (les bases déjà créées gardent leurs
# anciens mots de passe : supprimer aussi le volume postgres-data, données de démo perdues).

set -euo pipefail
cd "$(dirname "$0")/.."

FICHIER=".env.prod"
if [ -e "$FICHIER" ]; then
  echo "$FICHIER existe déjà : rien n'est modifié." >&2
  exit 1
fi

aleatoire() { openssl rand -hex 24; }

demander() {
  local invite="$1" valeur
  read -r -p "$invite : " valeur
  [ -n "$valeur" ] || { echo "Valeur obligatoire." >&2; exit 1; }
  printf '%s' "$valeur"
}

demander_secret() {
  local invite="$1" valeur
  read -r -s -p "$invite (saisie masquée) : " valeur
  echo >&2
  [ -n "$valeur" ] || { echo "Valeur obligatoire." >&2; exit 1; }
  printf '%s' "$valeur"
}

IP="$(demander "Adresse IP publique de la VM (ex. 141.145.10.20)")"
case "$IP" in
  *[!0-9.]* | "") echo "Adresse IP invalide." >&2; exit 1 ;;
esac
# sslip.io : <ip-avec-tirets>.sslip.io pointe vers l'IP, sans inscription ni DNS à gérer.
DOMAINE="$(printf '%s' "$IP" | tr '.' '-').sslip.io"
ACME_EMAIL="$(demander "E-mail pour Let's Encrypt (avis d'expiration des certificats)")"
echo "Brevo : Paramètres > SMTP & API > SMTP (identifiant de connexion et clé SMTP)."
SMTP_UTILISATEUR="$(demander "Identifiant SMTP Brevo")"
SMTP_MOT_DE_PASSE="$(demander_secret "Clé SMTP Brevo")"
SMTP_EXPEDITEUR="$(demander "Adresse d'expéditeur validée dans Brevo")"

umask 077
{
  echo "# Généré par scripts/vps-env.sh. Ne jamais commiter ni copier ailleurs."
  echo "DOMAINE=$DOMAINE"
  echo "IMAGE_TAG=local"
  echo "ACME_EMAIL=$ACME_EMAIL"
  echo "POSTGRES_USER=postgres"
  for nom in POSTGRES_PASSWORD ECHO_DB_PASSWORD KEYCLOAK_DB_PASSWORD CATALOGUE_DB_PASSWORD \
    BILLETS_DB_PASSWORD COMMANDES_DB_PASSWORD PAIEMENTS_DB_PASSWORD NOTIFICATIONS_DB_PASSWORD \
    RABBITMQ_DEFAULT_PASS KEYCLOAK_ADMIN_PASSWORD KEYCLOAK_SERVICES_SECRET \
    KEYCLOAK_REVENDEUR_SECRET KEYCLOAK_MDP_CLIENT KEYCLOAK_MDP_ADMIN QR_CLE_SIGNATURE \
    ADMISSION_CLE_SIGNATURE; do
    echo "$nom=$(aleatoire)"
  done
  echo "RABBITMQ_DEFAULT_USER=billetterie"
  echo "KEYCLOAK_ADMIN=admin"
  echo "KEYCLOAK_REALM=billetterie"
  # Salle d'attente sur la « Soirée jazz » du jeu de démonstration (comme en local).
  echo "SEANCES_SOUS_FILE=6b1f0c2e-4d5a-4e8b-9c11-0d0e0b000005"
  echo "SMTP_HOTE=smtp-relay.brevo.com"
  echo "SMTP_PORT=587"
  echo "SMTP_UTILISATEUR=$SMTP_UTILISATEUR"
  echo "SMTP_MOT_DE_PASSE=$SMTP_MOT_DE_PASSE"
  echo "SMTP_EXPEDITEUR=$SMTP_EXPEDITEUR"
  echo "# Front sur Vercel (https://<projet>.vercel.app) : CORS et redirections Keycloak."
  echo "URL_FRONT_VERCEL="
} > "$FICHIER"
chmod 600 "$FICHIER"

echo "$FICHIER écrit (droits 600). Domaine de la démo : https://$DOMAINE"
echo "Mots de passe de client.test et admin.test : grep KEYCLOAK_MDP $FICHIER (sur la VM seulement)."
echo "Étape suivante, depuis votre poste : bash scripts/deployer-vps.sh <utilisateur>@$IP"
