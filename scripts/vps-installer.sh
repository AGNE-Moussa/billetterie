#!/usr/bin/env bash
# Prépare une VM Ubuntu 24.04 neuve (Oracle Cloud Always Free, ARM) pour la démo (BIL-017).
# À lancer UNE fois, sur la VM, par l'utilisateur ubuntu :
#
#   curl -fsSL https://raw.githubusercontent.com/AGNE-Moussa/billetterie/main/scripts/vps-installer.sh -o vps-installer.sh
#   less vps-installer.sh      # relire avant d'exécuter
#   bash vps-installer.sh
#
# Installe Docker et Git depuis les dépôts Ubuntu, ouvre les ports 80 et 443 dans le pare-feu
# de l'image Oracle (iptables), ajoute de la mémoire d'échange et clone le dépôt dans
# /opt/billetterie. Aucun secret ici : .env.prod est écrit ensuite par scripts/vps-env.sh.

set -euo pipefail

DEPOT="https://github.com/AGNE-Moussa/billetterie.git"
DOSSIER="/opt/billetterie"

echo "1/5 Paquets : Docker, Compose, Git"
sudo apt-get update -q
sudo apt-get install -y -q docker.io docker-compose-v2 docker-buildx git iptables-persistent
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

echo "2/5 Pare-feu : ports 80 et 443"
# L'image Ubuntu d'Oracle rejette tout sauf SSH (règle REJECT) : les règles d'acceptation
# passent avant elle. La « Security List » du sous-réseau doit aussi ouvrir 80 et 443.
for port in 80 443; do
  if ! sudo iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT 5 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
  fi
done
sudo netfilter-persistent save

echo "3/5 Mémoire d'échange de 4 Go (constructions d'images)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
fi

echo "4/5 Dépôt dans $DOSSIER"
sudo mkdir -p "$DOSSIER"
sudo chown "$USER":"$USER" "$DOSSIER"
if [ ! -d "$DOSSIER/.git" ]; then
  git clone "$DEPOT" "$DOSSIER"
else
  git -C "$DOSSIER" pull --ff-only
fi

echo "5/5 Terminé."
echo "Déconnectez-vous puis reconnectez-vous (groupe docker), puis :"
echo "  cd $DOSSIER && bash scripts/vps-env.sh"
