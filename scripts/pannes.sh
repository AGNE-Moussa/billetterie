#!/usr/bin/env bash
# Scénarios de panne de l'infrastructure (BIL-F16), rejouables en direct pendant une démo.
#
#   scripts/pannes.sh echo       instance echo-1 tuée net (SIGKILL), puis relancée
#   scripts/pannes.sh rabbitmq   broker arrêté pendant les écritures, puis relancé
#   scripts/pannes.sh consul     registre arrêté, puis relancé
#   scripts/pannes.sh tous       les trois à la suite
#
# Pendant chaque panne, Newman rejoue postman/infra.json en boucle (créer puis relire un echo)
# et compte les appels en échec. À suivre dans Grafana : make observabilite, puis
# http://127.0.0.1:3000 (débit, erreurs, réponses de la gateway, instances, files).
#
# Prérequis : plateforme démarrée (make up ou make observabilite), Docker, .env renseigné.
# Résultats bruts : postman/resultats/ (ignoré par Git). Analyse : docs/pannes-infra.md.

set -euo pipefail
cd "$(dirname "$0")/.."
# Git Bash sous Windows : ne pas convertir les chemins passés à Docker (/etc/newman...).
export MSYS_NO_PATHCONV=1

IMAGE_NEWMAN="postman/newman:6.1.3-alpine"
ITERATIONS="${ITERATIONS:-150}"      # environ 40 s de trafic
PAUSE_MS="${PAUSE_MS:-100}"           # entre deux appels
DUREE_PANNE="${DUREE_PANNE:-15}"      # secondes de panne
RESULTATS="postman/resultats"

secret_services() {
  grep '^KEYCLOAK_SERVICES_SECRET=' .env | cut -d= -f2-
}

etape() {
  printf '\n\033[1m[%s] %s\033[0m\n' "$(date +%H:%M:%S)" "$*"
}

chemin_docker() {
  # Chemin hôte ABSOLU monté dans le conteneur (format Windows sous Git Bash). Un chemin
  # relatif serait pris par Docker pour le nom d'un volume, vide.
  if command -v cygpath >/dev/null 2>&1; then cygpath -aw "$1"; else realpath "$1"; fi
}

lancer_trafic() {
  local nom="$1"
  mkdir -p "$RESULTATS"
  docker rm -f "pannes-trafic-$nom" >/dev/null 2>&1 || true
  # Pas de --rm : le journal doit rester lisible une fois le trafic terminé.
  docker run -d --name "pannes-trafic-$nom" --network billetterie \
    -v "$(chemin_docker postman):/etc/newman:ro" \
    -e SECRET="$(secret_services)" \
    --entrypoint sh "$IMAGE_NEWMAN" \
    -c "newman run infra.json --env-var \"client_secret=\$SECRET\" -n $ITERATIONS \
        --delay-request $PAUSE_MS --reporters cli --reporter-cli-no-console" >/dev/null
  etape "Trafic lancé : $ITERATIONS fois « créer puis relire un echo » par la gateway"
}

bilan_trafic() {
  local nom="$1" journal="$RESULTATS/$1.log" sortie appels erreurs_reseau
  sortie=$(docker wait "pannes-trafic-$nom" 2>/dev/null || echo 99)
  docker logs "pannes-trafic-$nom" >"$journal" 2>&1 || true
  docker rm "pannes-trafic-$nom" >/dev/null 2>&1 || true
  etape "Bilan côté client ($journal)"
  appels=$(grep -cE '\[[0-9]{3} ' "$journal" || true)
  erreurs_reseau=$(grep -c '\[errored\]' "$journal" || true)
  echo "  Appels avec réponse : $appels ; erreurs réseau : $erreurs_reseau"
  echo "  Réponses par code HTTP :"
  grep -oE '\[[0-9]{3} ' "$journal" | tr -d '[ ' | sort | uniq -c | sed 's/^/   /' || true
  # Un trafic qui n'a pas tourné ne prouve rien : c'est un échec, pas « aucune erreur ».
  if [ "${appels:-0}" -eq 0 ]; then
    echo "  => ÉCHEC : aucun appel exécuté (voir $journal)"
    return 1
  elif [ "$sortie" = "0" ]; then
    echo "  => aucune erreur visible côté client"
  else
    echo "  => ERREURS visibles côté client (code de sortie de Newman : $sortie), détail dans $journal"
  fi
}

evenements_en_attente() {
  docker compose exec -T postgres psql -U echo -d echo -tAc \
    "select count(*) from outbox where envoye_le is null" 2>/dev/null | tr -d '[:space:]'
}

scenario_echo() {
  etape "SCÉNARIO 1 : une instance d'echo tombe"
  echo "  Hypothèse : echo-2 prend tout le trafic ; le client ne voit aucune erreur."
  lancer_trafic echo
  sleep 5
  etape "Panne : echo-1 tuée net (SIGKILL, sans se retirer de Consul)"
  docker compose kill echo-1 >/dev/null 2>&1
  sleep "$DUREE_PANNE"
  etape "Retour : echo-1 relancée (s'inscrit de nouveau dans Consul)"
  docker compose up -d --wait --no-deps echo-1 >/dev/null 2>&1
  bilan_trafic echo
}

scenario_rabbitmq() {
  etape "SCÉNARIO 2 : RabbitMQ s'arrête"
  echo "  Hypothèse : les écritures réussissent (201) ; les événements attendent dans l'outbox"
  echo "  et partent au retour du broker."
  lancer_trafic rabbitmq
  sleep 5
  etape "Panne : RabbitMQ arrêté"
  docker compose stop rabbitmq >/dev/null 2>&1
  sleep "$DUREE_PANNE"
  echo "  Événements en attente dans l'outbox d'echo : $(evenements_en_attente)"
  etape "Retour : RabbitMQ relancé"
  docker compose up -d --wait --no-deps rabbitmq >/dev/null 2>&1
  local attente=0
  while [ "$(evenements_en_attente)" != "0" ] && [ "$attente" -lt 60 ]; do
    sleep 2; attente=$((attente + 2))
  done
  echo "  Événements en attente $attente s après le retour du broker : $(evenements_en_attente)"
  bilan_trafic rabbitmq
}

scenario_consul() {
  etape "SCÉNARIO 3 : Consul s'arrête"
  echo "  Hypothèse : Traefik garde les dernières routes connues ; le client ne voit aucune"
  echo "  erreur ; au retour de Consul, les instances y figurent toujours."
  lancer_trafic consul
  sleep 5
  etape "Panne : Consul arrêté"
  docker compose stop consul >/dev/null 2>&1
  sleep "$DUREE_PANNE"
  etape "Retour : Consul relancé"
  docker compose up -d --wait --no-deps consul >/dev/null 2>&1
  sleep 10
  echo "  Instances d'echo dans Consul après son retour :"
  curl -s http://127.0.0.1:8500/v1/catalog/service/echo | grep -oE '"ServiceID": *"[^"]+"' \
    | sed 's/^/    /' || echo "    (aucune)"
  bilan_trafic consul
}

case "${1:-}" in
  echo) scenario_echo ;;
  rabbitmq) scenario_rabbitmq ;;
  consul) scenario_consul ;;
  tous) scenario_echo; scenario_rabbitmq; scenario_consul ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
