#!/bin/sh
# Crée une base et un utilisateur par service, avec le même nom.
# Exécuté par l'image postgres au premier démarrage sur un volume vide uniquement :
# pour le rejouer, supprimer le volume (make reset).
set -eu

for service in catalogue billets commandes paiements notifications; do
  variable="$(echo "$service" | tr '[:lower:]' '[:upper:]')_DB_PASSWORD"
  eval "mot_de_passe=\${$variable:?$variable manquant}"

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v service="$service" -v mot_de_passe="$mot_de_passe" <<'SQL'
CREATE ROLE :"service" LOGIN PASSWORD :'mot_de_passe';
CREATE DATABASE :"service" OWNER :"service";
-- Seul le propriétaire se connecte : un service ne peut pas lire la base d'un autre.
REVOKE ALL ON DATABASE :"service" FROM PUBLIC;
SQL

  echo "Base et utilisateur « $service » créés."
done
