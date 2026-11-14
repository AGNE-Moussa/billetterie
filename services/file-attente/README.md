# Service file-attente : salle d'attente virtuelle (BIL-015)

Généré depuis le modèle `services/echo/` ; écarts documentés ci-dessous.

## Routes

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/health` | Santé : l'instance et Redis répondent (503 sinon) ; exposée par Traefik sous `/api/v1/queues/health` (jeton requis) |
| `POST` | `/api/v1/queues/{seance_id}/position` | `entrerFile`, rôle `customer` : 201 en fin de file, 200 si déjà présent (position ou admission inchangée) |
| `GET` | `/api/v1/queues/{seance_id}/position` | `lirePositionFile`, rôle `customer` : `EN_ATTENTE` (position, attente estimée) ou `ADMIS` (jeton, échéance) |

Erreurs : 404 `QUEUE_NOT_FOUND` (séance hors `SEANCES_SOUS_FILE`), 404
`QUEUE_POSITION_NOT_FOUND`, 503 `FILE_INDISPONIBLE` (Redis injoignable ou trop lent). Le contrat
fait foi : `openapi.yaml`.

## Fonctionnement

- Une file par séance dans Redis : sorted set `file-attente:{<seance>}:attente` (membre `sub`,
  score l'horodatage d'entrée en ms, horloge de Redis). Chaque opération est un script Lua
  atomique : deux entrées simultanées du même client n'en font qu'une.
- Position 1 pour le prochain admis ; attente estimée `ceil(position / TAILLE_VAGUE) ×
  INTERVALLE_VAGUES`.
- Vagues : tâche périodique (`tache.py`), toutes les `INTERVALLE_VAGUES` secondes, protégée par
  un verrou Redis `SET NX PX` comme la tâche d'expiration de Commandes (une vague par intervalle
  pour toutes les instances). Elle retire les `TAILLE_VAGUE` premiers de la file et pose
  `file-attente:{<seance>}:admis:<sub>` avec expiration `DUREE_ADMISSION` (10 min par défaut).
- Jeton d'admission : `commun.admission` (HMAC-SHA256 de la séance, du `sub` et de l'échéance,
  clé `ADMISSION_CLE_SIGNATURE` partagée avec Commandes), recalculé à chaque lecture : le même
  jeton est rendu jusqu'à l'échéance. À l'échéance, la clé d'admission disparaît : le client
  n'est plus dans la file et rentre en fin de file s'il revient.
- Commandes vérifie le jeton localement dans `creerCommande` (en-tête `X-Admission-Token`), sans
  appel à ce service.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | file, admissions, verrou de tâche |
| `DELAI_REDIS` | `0.5` | attente maximale d'un appel Redis (s) |
| `SEANCES_SOUS_FILE` | vide | séances sous file, séparées par des virgules (mêmes valeurs que Commandes) |
| `ADMISSION_CLE_SIGNATURE` | vide | clé HMAC, au moins 32 caractères dès qu'une séance est sous file |
| `TAILLE_VAGUE` | `50` | clients admis par vague |
| `INTERVALLE_VAGUES` | `10` | secondes entre deux vagues |
| `DUREE_ADMISSION` | `600` | validité d'une admission (s) |
| `INSTANCE`, `PORT`, `CONSUL_ACTIF`, `JWT_*`, `JWKS_URL` | | comme echo |

## Écarts au modèle echo

- Ni base PostgreSQL, ni Alembic, ni outbox : l'état est éphémère et vit dans Redis ; aucun
  événement publié. Pas de `<nom>-migrations` dans le compose, pas de base dans
  `infra/postgres/init`. La santé vérifie Redis au lieu de la base.
- `Parametres` ignore les réglages inconnus (`extra="ignore"`) : le test de contrat commun passe
  `database_url` à chaque service.
- Le dossier `file-attente` contient un tiret, le paquet Python s'appelle `file_attente`
  (`src/file_attente/`) ; le test de contrat commun traduit `-` en `_`.
