# Tests de charge k6 (BIL-015)

Pic simulé sur une séance : mesure de référence **sans** file d'attente, puis **avec** file
d'attente. Les résultats (p95 et taux d'erreur, avant et après) sont reportés dans
`docs/charge.md` (CA2).

**Exécution locale uniquement, jamais en CI** (contrainte du ticket) : ces scripts chargent la
plateforme lancée par `make up` sur le poste.

| Fichier | Rôle |
|---|---|
| `commun.js` | configuration du pic, métriques, lecture du plan de salle, commande |
| `pic-sans-file.js` | référence : plan de salle puis `creerCommande` sans jeton d'admission |
| `pic-avec-file.js` | `entrerFile`, relecture de `lirePositionFile` jusqu'à `ADMIS`, puis commande avec `X-Admission-Token` |

## Prérequis

- k6 installé (`winget install k6` sous Windows) ;
- plateforme démarrée (`make up`) et jeu de démonstration chargé (`make demo`) ;
- l'identifiant d'une séance en vente (`SEANCE_ID`), avec des places libres ;
- des jetons d'accès clients, **un compte par utilisateur virtuel** (sinon la file d'attente ne
  voit qu'un client) :

  ```powershell
  uv run python infra/charge/comptes.py --nombre 200    # crée charge-001 à charge-200, écrit jetons.txt
  ```

  Le script crée les comptes dans le Keycloak **local** seulement (API d'administration, realm
  versionné inchangé), avec un mot de passe aléatoire jamais affiché, puis les connecte comme le
  front (PKCE). Les jetons vivent 5 minutes : lancer k6 juste après, avec
  `-e JETONS_FICHIER=jetons.txt`. Nettoyage : `uv run python infra/charge/comptes.py --supprimer`.
  À défaut, `JETONS` accepte des jetons copiés depuis le front connecté (en-tête
  `Authorization`), séparés par des virgules. Ne jamais écrire un jeton dans le dépôt.

## Mesure de référence (sans file)

La séance ne doit **pas** figurer dans `SEANCES_SOUS_FILE` (`.env`), puis :

```powershell
k6 run -e SEANCE_ID=<séance> -e JETONS_FICHIER=jetons.txt --summary-export charge-sans-file.json infra/charge/pic-sans-file.js
```

## Mesure avec file

Dans `.env` : `SEANCES_SOUS_FILE=<séance>` et `ADMISSION_CLE_SIGNATURE=<au moins 32 caractères>`
(par exemple `python -c "import secrets; print(secrets.token_urlsafe(32))"`), éventuellement
`TAILLE_VAGUE` et `INTERVALLE_VAGUES`. Recréer Commandes et file-attente pour relire la
configuration (`docker compose up -d commandes-1 commandes-2 file-attente-1 file-attente-2`),
puis :

```powershell
k6 run -e SEANCE_ID=<séance> -e JETONS_FICHIER=jetons.txt --summary-export charge-avec-file.json infra/charge/pic-avec-file.js
```

## Réglages (variables `-e`)

| Variable | Défaut | Rôle |
|---|---|---|
| `BASE_URL` | `http://localhost` | gateway Traefik |
| `VUS` | `200` | utilisateurs virtuels au plateau |
| `MONTEE`, `PLATEAU`, `DESCENTE` | `10s`, `40s`, `10s` | forme du pic |
| `RELECTURE` | `2` | secondes entre deux lectures de la position (avec file) |
| `ATTENTE_MAX` | `60` | attente maximale d'une admission par itération (avec file) |

## Lire les résultats

- `http_req_duration` p(95) : temps de réponse global ; `duree_creer_commande` p(95) : celui de
  `creerCommande` seul ; `attente_admission` : temps passé en file (avec file).
- `erreurs_techniques` : taux de réponses réseau, délai dépassé ou 5xx (saturation).
- `refus_metier` : 4xx attendus (409 place déjà prise ou plafond de 10 billets par client et par
  séance, 403 admission) ; ils ne mesurent pas la saturation.

Limite : tous les utilisateurs virtuels d'un même jeton sont le même client. Dans la file, ils
partagent une seule place (entrée idempotente) et sont admis ensemble ; et le plafond de billets
par client est vite atteint. Pour une mesure réaliste, fournir plusieurs jetons de clients
différents.
