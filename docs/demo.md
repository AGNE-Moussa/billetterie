# Démo de la billetterie (BIL-014)

Démo reproductible en moins de 15 minutes : le parcours complet joué par Newman, puis les quatre
pannes de services prévues par la conception (`docs/conception.md`, « Gestion des pannes »). Les
pannes de l'infrastructure (instance echo, RabbitMQ, Consul) sont dans `docs/pannes-infra.md`.

## Préparer (avant le public)

```sh
make up        # plateforme complète (attend healthy)
make demo      # jeu de démonstration du catalogue (Soirée jazz, utilisée par la panne Paiements)
```

- `.env` renseigné : `KEYCLOAK_MDP_CLIENT`, `KEYCLOAK_MDP_ADMIN`, `KEYCLOAK_REVENDEUR_SECRET`,
  `POSTGRES_USER` (variante `catalogue-base`). Les scripts les lisent et les passent aux conteneurs
  par l'environnement, jamais en argument ni dans un fichier versionné.
- Onglets ouverts : Mailpit http://127.0.0.1:8025 (e-mails), RabbitMQ http://127.0.0.1:15672
  (files), le front http://localhost, et Grafana http://127.0.0.1:3000 si démarré par
  `make observabilite`.
- Plafond de 10 billets par séance et par acheteur : la panne Paiements fait acheter une place de
  la Soirée jazz à `revendeur-test` à chaque passage. Après une dizaine de répétitions :
  `make reset`, `make up`, `make demo`.

## Déroulé minuté

| Temps | Étape | Commande | Ce qu'on montre |
|---|---|---|---|
| 0:00 | Contexte | | Microservices, verrou des places, une base par service |
| 1:00 | Parcours complet | `bash scripts/demo.sh parcours` | 44 requêtes, toutes vertes (détail plus bas) |
| 3:30 | Notifications arrêté | `bash scripts/demo.sh notifications` | Achat confirmé ; Mailpit inchangé ; e-mails partis au redémarrage |
| 6:30 | Catalogue arrêté | `bash scripts/demo.sh catalogue` | Achat refusé en 503 ; places et commandes toujours lisibles |
| 7:30 | Une instance de Billets tuée | `bash scripts/demo.sh billets` | Rafale d'achats sans aucune erreur |
| 10:00 | Paiements arrêté | `bash scripts/demo.sh paiements` | 503, commande en attente et place gardée ; nouvel essai payé |
| 11:00 | Bilan et questions | | Tableau prévu / observé de chaque scénario |

Tout d'un coup : `make demo-pannes` (`scripts/demo.sh tout`, environ 10 minutes). Les pannes
seules : `bash scripts/demo.sh pannes`. Chaque contrôle affiche `OK` ou `ÉCART`, la réponse
prévue et la réponse observée ; le script sort en code 1 s'il voit un écart.

## Le parcours complet (`postman/billetterie.json`)

Joué par `make parcours` : Newman en Docker sur le réseau `billetterie` (Traefik y répond sous
`traefik` et, par son alias, sous l'hôte des revendeurs). Chaque exécution crée sa propre séance :
la collection se rejoue sans `make reset` et n'abîme pas le jeu de démonstration.

1. **Jetons** : `client.test` et `admin.test` par Authorization Code + PKCE, `revendeur-test` par
   Client Credentials.
2. **Organisateur** : 401 sans jeton, 403 avec le jeton du client, puis lieu, événement et séance
   de 30 places (rang A à 50 €, rang B à 25 €).
3. **Catalogue public** : recherche, événement, séances, séance, puis attente des 30 places créées
   par Billets (`ticketing.show.scheduled`).
4. **Réserver puis payer** : commande sans carte (201 EN_ATTENTE), rejeu de la même
   `Idempotency-Key` (200, même commande), places indisponibles, la même place visée par le
   revendeur (409 SEAT_ALREADY_TAKEN), paiement (200 CONFIRMEE), second paiement (409
   ORDER_NOT_PENDING), carte refusée (402 PAYMENT_REFUSED).
5. **Suivi** : commande, liste, attente des deux billets émis, billet et son QR code.
6. **Rafale** : `rafale_taille` achats payés à la suite (3 par défaut, 6 pendant la panne de
   Billets).
7. **Revendeur** : catalogue, places, commande payée, suivi, isolation (404 ORDER_NOT_FOUND sur la
   commande du client, 403 ROLE_MANQUANT sur l'hôte standard), billet.
8. **Annulation** : séance annulée (200), seconde annulation (409), séance lue annulée, achat
   refusé (409 SHOW_CANCELLED), puis commandes REMBOURSEE et billet ANNULE.

Les étapes asynchrones (places, billets, remboursements) sont attendues par une requête rejouée
toutes les `attente_ms` (1 s), au plus `tentatives_max` fois (40).

### Jetons utilisateur : PKCE dans Newman

Le client `frontend` est public et n'accepte que l'Authorization Code avec PKCE (Direct Access
Grant désactivé, et laissé tel quel). Newman n'ouvre pas de navigateur, mais le parcours n'est que
du HTTP ; la collection le joue comme `tests/smoke/test_comptes.py` :

1. un script calcule `code_verifier` (aléatoire) et `code_challenge` (SHA-256 en base64url, avec
   CryptoJS du bac à sable Postman), puis `GET /auth` affiche la page de connexion ;
2. le test de la réponse extrait l'action du formulaire `kc-form-login` et les cookies de
   session ; `POST` du formulaire (identifiant, mot de passe passé par `--env-var`), redirection
   non suivie : le `code` est lu dans l'en-tête `Location` ;
3. `POST /token` échange le code et le `code_verifier` contre le jeton.

Deux détails : les cookies Keycloak portent l'attribut `Secure`, que le pot à cookies ne renvoie
pas en HTTP, d'où l'en-tête `Cookie` recopié à la main (`disableCookies`) ; Keycloak écrit son
adresse publique (`http://localhost/auth`) dans l'action du formulaire, que la collection rejoue
sur `base_url` (`http://traefik` depuis le réseau Docker). Limite : la collection dépend du
gabarit HTML de la page de connexion (identifiant `kc-form-login`) ; un thème Keycloak qui le
change casse l'étape 2, comme le smoke test.

### Depuis Postman sur le poste

Importer `postman/billetterie.json`, garder `base_url=http://localhost` et
`base_partenaires=http://partenaires.localhost`, renseigner `mdp_client`, `mdp_admin` et
`revendeur_secret` dans un environnement Postman local (jamais exporté dans le dépôt), puis lancer
le runner.

## Les pannes et la réponse prévue

| Scénario | Panne provoquée | Prévu (conception) | Contrôles du script |
|---|---|---|---|
| Notifications | `docker compose stop notifications-1` pendant le parcours complet | Achat confirmé ; messages gardés dans RabbitMQ, envoyés au redémarrage | Collection verte ; total Mailpit inchangé ; messages en file ; total en hausse après le retour |
| Catalogue | `docker compose stop catalogue-1` | 200 depuis le cache, sinon 503 | Lecture : 200 ou 503 ; achat : 503 SERVICE_INDISPONIBLE ; places et commandes : 200 |
| Billets (une instance) | `docker compose kill billets-1` pendant le parcours et sa rafale, 20 s | Aucun impact visible | Collection verte, rafale comprise |
| Paiements | `docker compose stop paiements-1` entre réservation et paiement | 503 avec invitation à réessayer ; commande en attente, place verrouillée | 503 SERVICE_INDISPONIBLE ; EN_ATTENTE ; place indisponible ; nouvel essai : 200 CONFIRMEE |

Durées réglables : `DUREE_PANNE` (Billets, 20 s), `RAFALE` (6 achats, 7 au plus).

## Écarts connus avec la conception

- **Catalogue arrêté** : le cache Redis est lu par le service Catalogue lui-même, quand *sa base*
  ne répond pas (BIL-005, en-tête `X-Cache-Stale: true`). Quand l'instance est arrêtée, plus rien
  ne le sert : Consul la retire, Traefik n'a plus de route et répond 404 (texte brut) aux lectures
  du catalogue, ni 200 ni 503. Le script le signale en `ÉCART`. L'achat, lui, répond bien 503
  SERVICE_INDISPONIBLE (Commandes ne peut pas lire la séance).
- **Base du Catalogue coupée** (`bash scripts/demo.sh catalogue-base`, hors enchaînement) : montre
  le vrai chemin du cache. Le rôle `catalogue` est passé `NOLOGIN` et ses connexions coupées, puis
  rétabli (même sur Ctrl+C). Une liste déjà lue répond 200 avec `X-Cache-Stale: true`, une
  lecture jamais mise en cache 503 BASE_INDISPONIBLE. Attendu ensuite : au check Consul suivant
  (10 s), `/health` répond 503, l'instance quitte Traefik et la copie de secours n'est plus
  joignable (404) ; le script le contrôle à 12 s.

Résultats à reporter ici après la première exécution contre `make up` (date, durées, écarts).
