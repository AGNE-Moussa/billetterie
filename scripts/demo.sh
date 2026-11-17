#!/usr/bin/env bash
# Démo reproductible de la billetterie (BIL-014) : parcours complet et pannes des services.
#
#   scripts/demo.sh parcours        parcours complet (postman/billetterie.json) joué par Newman
#   scripts/demo.sh notifications   Notifications arrêté pendant un achat, e-mails au redémarrage
#   scripts/demo.sh catalogue       Catalogue arrêté : lectures, achat, consultation
#   scripts/demo.sh catalogue-base  base du Catalogue coupée : lectures depuis le cache Redis
#   scripts/demo.sh billets         une instance de Billets tuée pendant une rafale d'achats
#   scripts/demo.sh paiements       Paiements arrêté au moment de payer, puis nouvel essai
#   scripts/demo.sh pannes          les quatre pannes de la conception à la suite
#   scripts/demo.sh tout            parcours, puis les quatre pannes (moins de 15 minutes)
#
# Chaque scénario affiche la réponse prévue par la conception (docs/conception.md, « Gestion des
# pannes ») face à la réponse observée, puis un bilan ; code de sortie 1 si un écart est vu.
# Prérequis : plateforme démarrée (make up), jeu de démonstration chargé (make demo), Docker,
# uv, .env renseigné. Journaux de Newman : postman/resultats/ (ignoré par Git). Déroulé : docs/demo.md.

set -euo pipefail
cd "$(dirname "$0")/.."
# Git Bash sous Windows : ne pas convertir les chemins passés à Docker (/etc/newman...).
export MSYS_NO_PATHCONV=1

IMAGE_NEWMAN="postman/newman:6.1.3-alpine"
GATEWAY="http://localhost"
MAILPIT="http://127.0.0.1:8025"
RESULTATS="postman/resultats"
DUREE_PANNE="${DUREE_PANNE:-20}"         # secondes d'arrêt d'une instance de Billets
RAFALE="${RAFALE:-6}"                    # achats de la rafale (plafond : 10 billets par séance)
SOIREE_JAZZ="6b1f0c2e-4d5a-4e8b-9c11-0d0e0b000005"   # séance du jeu de démonstration (make demo)
ECARTS=0

# --- Outils -------------------------------------------------------------------------------

lire_env() {
  # Valeur d'une variable de .env, sans guillemets ; jamais affichée.
  grep "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']\$//"
}

REALM="$(lire_env KEYCLOAK_REALM)"; REALM="${REALM:-billetterie}"
HOTE_PARTENAIRES="$(lire_env HOTE_PARTENAIRES)"; HOTE_PARTENAIRES="${HOTE_PARTENAIRES:-partenaires.localhost}"

etape() {
  printf '\n\033[1m[%s] %s\033[0m\n' "$(date +%H:%M:%S)" "$*"
}

json() {
  # Lit un JSON sur l'entrée standard et affiche l'expression Python $1 (d = document).
  uv run --quiet python -c "import json, sys
try:
    d = json.load(sys.stdin)
    print($1)
except Exception:
    print('')"
}

chemin_docker() {
  # Chemin hôte ABSOLU monté dans le conteneur (format Windows sous Git Bash).
  if command -v cygpath >/dev/null 2>&1; then cygpath -aw "$1"; else realpath "$1"; fi
}

# appel MÉTHODE CHEMIN [JETON] [CORPS] [HÔTE] : remplit STATUT, CORPS et EN_TETES.
appel() {
  local methode="$1" chemin="$2" jeton="${3:-}" corps="${4:-}" hote="${5:-}" fichier entetes
  fichier="$(mktemp)"; entetes="$(mktemp)"
  local options=(-s -o "$fichier" -D "$entetes" -w '%{http_code}' -X "$methode" --max-time 30)
  [ -n "$jeton" ] && options+=(-H "Authorization: Bearer $jeton")
  [ -n "$hote" ] && options+=(-H "Host: $hote")
  [ -n "$corps" ] && options+=(-H "Content-Type: application/json" -H "Idempotency-Key: demo-$RANDOM$RANDOM$RANDOM" -d "$corps")
  STATUT="$(curl "${options[@]}" "$GATEWAY$chemin" || echo 000)"
  CORPS="$(cat "$fichier")"
  EN_TETES="$(tr -d '\r' <"$entetes")"
  rm -f "$fichier" "$entetes"
}

code_metier() { printf '%s' "$CORPS" | json 'd.get("code", "")'; }

# verifier LIBELLÉ PRÉVU OBSERVÉ : compare et compte les écarts.
verifier() {
  if [ "$2" = "$3" ]; then
    printf '  \033[32mOK\033[0m     %-58s prévu %-28s observé %s\n' "$1" "$2" "$3"
  else
    printf '  \033[31mÉCART\033[0m  %-58s prévu %-28s observé %s\n' "$1" "$2" "$3"
    ECARTS=$((ECARTS + 1))
  fi
}

jeton_revendeur() {
  # Client Credentials ; le secret passe par l'entrée standard de curl, jamais en argument.
  local secret
  secret="$(lire_env KEYCLOAK_REVENDEUR_SECRET)"
  [ -n "$secret" ] || { echo "KEYCLOAK_REVENDEUR_SECRET absent de .env" >&2; exit 2; }
  printf '%s' "$secret" | curl -s --max-time 15 \
    -d grant_type=client_credentials -d client_id=revendeur-test --data-urlencode client_secret@- \
    "$GATEWAY/auth/realms/$REALM/protocol/openid-connect/token" | json 'd["access_token"]'
}

place_libre_jazz() {
  appel GET "/api/v1/seats?seance_id=$SOIREE_JAZZ&size=100"
  printf '%s' "$CORPS" | json 'next(p["id"] for p in d["elements"] if p["disponible"])'
}

total_mailpit() {
  curl -s --max-time 5 "$MAILPIT/api/v1/messages?limit=1" | json 'd.get("total", d.get("messages_count", 0))'
}

messages_en_file_notifications() {
  docker compose exec -T rabbitmq rabbitmqctl -q list_queues name messages 2>/dev/null \
    | grep -i notif | awk '{ somme += $2 } END { print somme + 0 }'
}

# newman_parcours NOM [détaché] [--env-var ...] : postman/billetterie.json sur le réseau billetterie.
newman_parcours() {
  local nom="$1" mode="$2"; shift 2
  local supplement="$*"
  mkdir -p "$RESULTATS"
  docker rm -f "demo-$nom" >/dev/null 2>&1 || true
  # Secrets transmis par l'environnement du conteneur (-e NOM sans valeur), jamais en argument.
  MDP_CLIENT="$(lire_env KEYCLOAK_MDP_CLIENT)" MDP_ADMIN="$(lire_env KEYCLOAK_MDP_ADMIN)" \
  REVENDEUR_SECRET="$(lire_env KEYCLOAK_REVENDEUR_SECRET)" \
  docker run -d --name "demo-$nom" --network billetterie \
    -v "$(chemin_docker postman):/etc/newman:ro" \
    -e MDP_CLIENT -e MDP_ADMIN -e REVENDEUR_SECRET \
    --entrypoint sh "$IMAGE_NEWMAN" \
    -c "newman run billetterie.json \
        --env-var \"mdp_client=\$MDP_CLIENT\" --env-var \"mdp_admin=\$MDP_ADMIN\" \
        --env-var \"revendeur_secret=\$REVENDEUR_SECRET\" \
        --env-var base_url=http://traefik --env-var base_partenaires=http://$HOTE_PARTENAIRES \
        $supplement --reporters cli --reporter-cli-no-console" >/dev/null
  [ "$mode" = "detache" ] || bilan_newman "$nom"
}

# bilan_newman NOM : attend la fin de Newman, garde son journal, remplit NEWMAN_SORTIE.
bilan_newman() {
  local nom="$1" journal="$RESULTATS/$1.log"
  NEWMAN_SORTIE="$(docker wait "demo-$nom" 2>/dev/null || echo 99)"
  docker logs "demo-$nom" >"$journal" 2>&1 || true
  docker rm "demo-$nom" >/dev/null 2>&1 || true
  echo "  Newman ($journal) :"
  grep -E '│ +(requests|test-scripts|assertions) ' "$journal" | sed 's/^/    /' || true
  grep -E '^ *[0-9]+\. +(AssertionError|Error)' -A2 "$journal" | head -20 | sed 's/^/    /' || true
}

# --- Parcours -------------------------------------------------------------------------------

scenario_parcours() {
  etape "PARCOURS COMPLET : postman/billetterie.json"
  echo "  Jetons (PKCE client.test et admin.test, Client Credentials revendeur), séance créée par"
  echo "  l'organisateur, réservation, paiement, billets, rafale, revendeur, annulation."
  newman_parcours parcours attendre
  verifier "Toutes les assertions de la collection passent" "0" "$NEWMAN_SORTIE"
}

# --- Pannes ---------------------------------------------------------------------------------

scenario_notifications() {
  etape "PANNE 1 : Notifications arrêté"
  echo "  Conception : messages conservés dans RabbitMQ, envoyés au redémarrage ; achat confirmé"
  echo "  normalement."
  local avant pendant apres attente=0
  avant="$(total_mailpit)"
  etape "Arrêt de notifications-1, puis parcours complet pendant la panne"
  docker compose stop notifications-1 >/dev/null 2>&1
  newman_parcours notifications attendre
  verifier "Achat confirmé normalement (collection verte)" "0" "$NEWMAN_SORTIE"
  pendant="$(total_mailpit)"
  verifier "Aucun e-mail envoyé pendant la panne" "$avant" "$pendant"
  echo "  Messages en attente dans les files de Notifications : $(messages_en_file_notifications)"
  etape "Retour : notifications-1 relancé"
  docker compose up -d --wait --no-deps notifications-1 >/dev/null 2>&1
  apres="$pendant"
  while [ "$apres" = "$pendant" ] && [ "$attente" -lt 60 ]; do
    sleep 2; attente=$((attente + 2)); apres="$(total_mailpit)"
  done
  echo "  E-mails dans Mailpit : $avant avant, $pendant pendant, $apres $attente s après le retour"
  echo "  (boîte : $MAILPIT)"
  verifier "E-mails partis au redémarrage" "oui" "$([ "${apres:-0}" -gt "${pendant:-0}" ] && echo oui || echo non)"
  echo "  Messages encore en file : $(messages_en_file_notifications)"
}

scenario_catalogue() {
  etape "PANNE 2 : Catalogue arrêté"
  echo "  Conception : lecture depuis le cache Redis, 200 avec données en cache, sinon 503."
  local jeton
  jeton="$(jeton_revendeur)"
  appel GET "/api/v1/events?size=5"; appel GET "/api/v1/events?size=5"   # cache réchauffé
  etape "Arrêt de catalogue-1 (seule instance)"
  docker compose stop catalogue-1 >/dev/null 2>&1
  sleep 3
  appel GET "/api/v1/events?size=5"
  verifier "Lire le catalogue : 200 depuis le cache, sinon 503" "200 ou 503" \
    "$([ "$STATUT" = 200 ] || [ "$STATUT" = 503 ] && echo '200 ou 503' || echo "$STATUT")"
  [ "$STATUT" = 200 ] && echo "  X-Cache-Stale : $(grep -i '^x-cache-stale' <<<"$EN_TETES" | cut -d' ' -f2 || true)"
  appel POST "/api/v1/orders" "$jeton" "{\"seance_id\": \"$SOIREE_JAZZ\", \"place_ids\": [\"$(place_libre_jazz)\"]}" "$HOTE_PARTENAIRES"
  verifier "Commander : séance illisible, achat refusé proprement" "503 SERVICE_INDISPONIBLE" "$STATUT $(code_metier)"
  appel GET "/api/v1/seats?seance_id=$SOIREE_JAZZ&size=5"
  verifier "Disponibilité des places (Billets) intacte" "200" "$STATUT"
  appel GET "/api/v1/orders?size=5" "$jeton" "" "$HOTE_PARTENAIRES"
  verifier "Suivi des commandes (Commandes) intact" "200" "$STATUT"
  etape "Retour : catalogue-1 relancé"
  docker compose up -d --wait --no-deps catalogue-1 >/dev/null 2>&1
  local attente=0
  appel GET "/api/v1/events?size=5"
  while [ "$STATUT" != 200 ] && [ "$attente" -lt 30 ]; do
    sleep 2; attente=$((attente + 2)); appel GET "/api/v1/events?size=5"
  done
  verifier "Catalogue de nouveau servi ($attente s après le retour)" "200" "$STATUT"
}

scenario_catalogue_base() {
  etape "PANNE 2 bis : base du Catalogue coupée (l'instance tourne)"
  echo "  Conception : 200 avec données en cache (en-tête X-Cache-Stale: true), sinon 503."
  appel GET "/api/v1/events?size=5"; appel GET "/api/v1/events?size=5"   # cache réchauffé
  # Super-utilisateur du serveur, par le socket local du conteneur (sans mot de passe).
  sql() { docker compose exec -T postgres psql -U "$(lire_env POSTGRES_USER)" -d postgres -qtAc "$1" >/dev/null; }
  # Rétablie quoi qu'il arrive, même sur Ctrl+C.
  trap 'sql "ALTER ROLE catalogue LOGIN" || true' EXIT
  etape "Connexions du rôle catalogue refusées et coupées (ALTER ROLE ... NOLOGIN)"
  sql "ALTER ROLE catalogue NOLOGIN"
  sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'catalogue'"
  sleep 2
  appel GET "/api/v1/events?size=5"
  verifier "Liste déjà lue : copie de secours du cache" "200 true" \
    "$STATUT $(grep -i '^x-cache-stale' <<<"$EN_TETES" | cut -d' ' -f2 || echo absent)"
  appel GET "/api/v1/events?size=5&q=jamais-lu-$RANDOM"
  verifier "Lecture jamais mise en cache" "503 BASE_INDISPONIBLE" "$STATUT $(code_metier)"
  echo "  Après le prochain check Consul (10 s), /health répond 503 et l'instance quitte Traefik :"
  sleep 12
  appel GET "/api/v1/events?size=5"
  verifier "Liste déjà lue, 12 s plus tard" "200 true" \
    "$STATUT $(grep -i '^x-cache-stale' <<<"$EN_TETES" | cut -d' ' -f2 || echo absent)"
  etape "Retour : connexions du rôle catalogue rétablies"
  sql "ALTER ROLE catalogue LOGIN"
  trap - EXIT
  local attente=0
  appel GET "/api/v1/events?size=5"
  while { [ "$STATUT" != 200 ] || grep -qi '^x-cache-stale' <<<"$EN_TETES"; } && [ "$attente" -lt 30 ]; do
    sleep 2; attente=$((attente + 2)); appel GET "/api/v1/events?size=5"
  done
  verifier "Catalogue servi par la base ($attente s après le retour)" "200" "$STATUT"
}

scenario_billets() {
  etape "PANNE 3 : une instance de Billets tuée pendant une rafale d'achats"
  echo "  Conception : l'autre instance prend le relais par le load balancing ; aucun impact visible."
  newman_parcours billets detache --env-var "rafale_taille=$RAFALE"
  etape "Parcours lancé (rafale de $RAFALE achats) ; billets-1 tuée net dans 5 s"
  sleep 5
  docker compose kill billets-1 >/dev/null 2>&1
  etape "Panne : billets-1 arrêtée pendant $DUREE_PANNE s (SIGKILL, sans se retirer de Consul)"
  sleep "$DUREE_PANNE"
  etape "Retour : billets-1 relancée"
  docker compose up -d --wait --no-deps billets-1 >/dev/null 2>&1
  bilan_newman billets
  verifier "Parcours et rafale sans aucune erreur visible" "0" "$NEWMAN_SORTIE"
}

scenario_paiements() {
  etape "PANNE 4 : Paiements arrêté au moment de payer"
  echo "  Conception : commande en attente, place verrouillée jusqu'à expiration ; 503 avec"
  echo "  invitation à réessayer."
  local jeton place commande attente=0
  jeton="$(jeton_revendeur)"
  place="$(place_libre_jazz)"
  [ -n "$place" ] || { echo "  Aucune place libre sur la Soirée jazz : make demo, ou make reset puis make demo"; exit 2; }
  appel POST "/api/v1/orders" "$jeton" "{\"seance_id\": \"$SOIREE_JAZZ\", \"place_ids\": [\"$place\"]}" "$HOTE_PARTENAIRES"
  if [ "$(code_metier)" = TICKET_LIMIT_EXCEEDED ]; then
    echo "  Plafond de 10 billets par séance atteint par revendeur-test : make reset puis make demo"; exit 2
  fi
  verifier "Réserver sans carte (Paiements pas encore appelé)" "201" "$STATUT"
  commande="$(printf '%s' "$CORPS" | json 'd["id"]')"
  etape "Arrêt de paiements-1 (seule instance)"
  docker compose stop paiements-1 >/dev/null 2>&1
  appel POST "/api/v1/orders/$commande/payment" "$jeton" '{"carte_test": "4242424242424242"}' "$HOTE_PARTENAIRES"
  verifier "Payer" "503 SERVICE_INDISPONIBLE" "$STATUT $(code_metier)"
  echo "  Message au client : $(printf '%s' "$CORPS" | json 'd.get("detail", "")')"
  appel GET "/api/v1/orders/$commande" "$jeton" "" "$HOTE_PARTENAIRES"
  verifier "Commande toujours en attente, aucun débit" "EN_ATTENTE" "$(printf '%s' "$CORPS" | json 'd["statut"]')"
  echo "  Place verrouillée jusqu'à : $(printf '%s' "$CORPS" | json 'd["expire_le"]')"
  appel GET "/api/v1/seats?seance_id=$SOIREE_JAZZ&size=100"
  verifier "Place toujours verrouillée pour la commande" "False" \
    "$(printf '%s' "$CORPS" | json "next(p['disponible'] for p in d['elements'] if p['id'] == '$place')")"
  etape "Retour : paiements-1 relancé ; le client réessaie"
  docker compose up -d --wait --no-deps paiements-1 >/dev/null 2>&1
  appel POST "/api/v1/orders/$commande/payment" "$jeton" '{"carte_test": "4242424242424242"}' "$HOTE_PARTENAIRES"
  while [ "$STATUT" = 503 ] && [ "$attente" -lt 40 ]; do
    sleep 2; attente=$((attente + 2))
    appel POST "/api/v1/orders/$commande/payment" "$jeton" '{"carte_test": "4242424242424242"}' "$HOTE_PARTENAIRES"
  done
  verifier "Nouvel essai ($attente s après le retour) : commande payée" "200 CONFIRMEE" \
    "$STATUT $(printf '%s' "$CORPS" | json 'd.get("statut", d.get("code", ""))')"
}

bilan() {
  etape "BILAN"
  if [ "$ECARTS" -eq 0 ]; then
    echo "  Tous les comportements observés sont ceux prévus par la conception."
  else
    echo "  $ECARTS écart(s) avec la conception : voir docs/demo.md (écarts connus)."
    exit 1
  fi
}

DEBUT=$(date +%s)
case "${1:-}" in
  parcours) scenario_parcours ;;
  notifications) scenario_notifications ;;
  catalogue) scenario_catalogue ;;
  catalogue-base) scenario_catalogue_base ;;
  billets) scenario_billets ;;
  paiements) scenario_paiements ;;
  pannes) scenario_notifications; scenario_catalogue; scenario_billets; scenario_paiements ;;
  tout) scenario_parcours; scenario_notifications; scenario_catalogue; scenario_billets; scenario_paiements ;;
  *) sed -n '2,11p' "$0"; exit 2 ;;
esac
echo; echo "  Durée : $(( $(date +%s) - DEBUT )) s"
bilan
