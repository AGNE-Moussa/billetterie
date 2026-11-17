# Déployer la démo en ligne (BIL-017)

Toute la plateforme tourne sur **une VM gratuite** : Oracle Cloud « Always Free », ARM, 4 cœurs,
24 Go. Elle porte PostgreSQL, Redis, RabbitMQ, Keycloak, Traefik, Consul et les services. Le
front est servi par la VM et, en plus, par **Vercel**, gratuit avec un CDN. Les e-mails passent
par **Brevo**, gratuit jusqu'à 300 par jour.

Le domaine est `<ip-avec-tirets>.sslip.io` : il est gratuit et ne demande ni inscription ni
DNS. Le certificat HTTPS vient de Let's Encrypt, obtenu par Traefik.

```text
navigateur ──https──> <ip>.sslip.io (VM) ── Traefik ── services, Keycloak, front
           ──https──> <projet>.vercel.app (front seul) ──> API et /auth de la VM
```

Pourquoi pas Render, ni Neon :
- **Render** : l'offre gratuite donne 512 Mo et 750 heures par mois pour tout le compte, avec
  mise en veille. Keycloak seul dépasse ces limites, et une douzaine de services 24 h/24 aussi.
- **Neon** : les relais d'outbox interrogent la base chaque seconde, donc la base ne se met
  jamais en veille. Le quota d'heures de calcul gratuit serait épuisé avant la fin du mois.

## 1. Ce que vous créez (comptes et clés, jamais dans le dépôt)

1. **Oracle Cloud** (https://signup.cloud.oracle.com) :
   - une carte bancaire est demandée pour vérifier l'identité, sans débit en Always Free ;
   - créer une instance *VM.Standard.A1.Flex* (4 OCPU, 24 Go, Ubuntu 24.04) et télécharger sa
     clé SSH privée ;
   - dans la *Security List* du sous-réseau, ouvrir TCP 80 et 443 depuis `0.0.0.0/0`.

   Si vous obtenez « Out of capacity », réessayez plus tard ou dans une autre zone.
2. **Brevo** (https://www.brevo.com) :
   - *Paramètres > SMTP & API > SMTP* : noter l'identifiant de connexion, puis générer une clé
     SMTP ;
   - *Expéditeurs* : valider l'adresse d'envoi.
3. **Vercel** (https://vercel.com) : se connecter avec GitHub.

## 2. Préparer la VM (une fois)

Depuis votre poste, avec la clé SSH d'Oracle :

```sh
ssh -i <clé-oracle> ubuntu@<ip>
curl -fsSL https://raw.githubusercontent.com/AGNE-Moussa/billetterie/main/scripts/vps-installer.sh -o vps-installer.sh
less vps-installer.sh        # relire avant d'exécuter
bash vps-installer.sh        # Docker, pare-feu 80/443, swap, dépôt dans /opt/billetterie
exit                         # reconnexion pour le groupe docker
ssh -i <clé-oracle> ubuntu@<ip>
cd /opt/billetterie && bash scripts/vps-env.sh
```

`vps-env.sh` écrit `/opt/billetterie/.env.prod` (droits 600) :
- les mots de passe et clés internes sont tirés au hasard sur la VM ;
- il vous demande l'IP, l'e-mail Let's Encrypt et les identifiants Brevo, en saisie masquée ;
- rien ne sort de la VM.

Les mots de passe de `client.test` et `admin.test` se lisent sur la VM :
`grep KEYCLOAK_MDP .env.prod`.

## 3. Déployer (et redéployer)

Depuis votre poste (Git Bash), la clé chargée dans l'agent (`ssh-add <clé-oracle>`) :

```sh
bash scripts/deployer-vps.sh ubuntu@<ip>             # branche main
bash scripts/deployer-vps.sh ubuntu@<ip> <branche>   # une branche poussée sur GitHub
```

Le script fait, sur la VM :
1. `git pull` du dépôt ;
2. construction des images ARM sur la VM ;
3. `up -d --wait` ;
4. chargement du jeu de démonstration (idempotent).

Le premier déploiement prend 15 à 25 minutes, à cause des constructions et de Keycloak ; les
suivants, quelques minutes. La démo répond ensuite sur `https://<ip-avec-tirets>.sslip.io`.

Une fois GitHub Actions disponible, `.github/workflows/deploiement.yml` fait la même chose en un
clic, avec les images de GHCR. Il faut les secrets d'environnement `VPS_*`, `GHCR_UTILISATEUR`
et `GHCR_TOKEN`. Le retour arrière se fait avec l'entrée `tag`.

## 4. Front sur Vercel

1. Créer le projet depuis le dépôt GitHub, avec le dossier racine `frontend`.
   `frontend/vercel.json` fixe le build et le repli SPA.
2. Variables d'environnement du projet :
   - `VITE_API_URL=https://<domaine>/api` ;
   - `VITE_KEYCLOAK_URL=https://<domaine>/auth`.
3. Sur la VM, dans `.env.prod` : `URL_FRONT_VERCEL=https://<projet>.vercel.app`, puis
   redéployer. Cette variable alimente les CORS de Traefik et les redirections du client
   `frontend` de Keycloak.

Le realm est importé une seule fois. Si la VM tournait déjà quand vous ajoutez Vercel, déclarez
l'origine dans la console Keycloak : *Clients > frontend*, rubriques *Valid redirect URIs*,
*Web origins* et *Valid post logout redirect URIs*.

## 5. Vérifier

```sh
URL_PLATEFORME=https://<domaine> uv run pytest tests/smoke/test_plateforme.py tests/smoke/test_places.py
```

Les autres smoke tests lisent les mots de passe des comptes de test dans le `.env` local. Ceux de
la démo restent sur la VM : la connexion se vérifie donc dans le navigateur.

Dans le navigateur :
1. le catalogue s'affiche ;
2. « Créer un compte » envoie un e-mail de confirmation, reçu dans une vraie boîte ;
3. un achat avec la carte `4242 4242 4242 4242` se termine par un billet avec QR code, envoyé
   par e-mail.

## Limites du gratuit

- **VM Oracle** : une instance Always Free inactive peut être récupérée par Oracle. La démo
  tourne en continu, ce qui limite ce risque. Il n'y a pas de sauvegarde : les données de démo
  se rechargent avec le script.
- **sslip.io** : le domaine dépend de l'IP. Si l'IP change, relancer `vps-env.sh` après avoir
  supprimé `.env.prod`.
- **Brevo** : 300 e-mails par jour.
- **Let's Encrypt** : 5 certificats par semaine pour un même nom. Ne pas supprimer le volume
  `traefik-acme` sans raison.
