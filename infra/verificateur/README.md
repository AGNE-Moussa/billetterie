# Vérificateur de jetons (ForwardAuth)

Petit service FastAPI appelé par Traefik avant chaque requête routée par les chaînes `standard`
et `partenaires` de `infra/traefik/dynamique.yml`. Chaque chaîne a sa propre adresse (BIL-012) :

| Chaîne | Middleware | Adresse | Rôles admis |
|---|---|---|---|
| `standard@file` | `verification-jeton` | `/verifier` | tout jeton sans le rôle `partner` |
| `partenaires@file` (hôte `HOTE_PARTENAIRES`) | `verification-jeton-partenaires` | `/verifier/partenaires` | jeton portant le rôle `partner` |

Un revendeur ne contourne donc pas son quota (`limite-partenaires`) en passant par l'hôte
standard, et l'hôte des partenaires ne sert que les revendeurs. Règle : `verificateur.chaines`.

```text
client ──► Traefik ──(en-têtes de la requête)──► verificateur /verifier[/partenaires]
                │                                   │ 200 + X-User-Id, X-User-Roles, X-Client-Id
                │◄──────────────────────────────────┘ ou 401 / 403 / 503 (Problem Details)
                └──► service (seulement sur 200, avec les en-têtes X-User-*)
```

## Ce qui est vérifié

La validation est celle de `libs/commun/jetons.py`, partagée avec les services (qui revérifient
le jeton avec `commun.auth`).

- Signature RS256 avec les clés publiques du realm (JWKS), gardées en cache : aucun appel à
  Keycloak par requête. Rechargement après `JWKS_DUREE_CACHE` secondes ou sur un `kid` inconnu
  (rotation de clé), au plus une fois toutes les `JWKS_INTERVALLE_MIN` secondes.
- `exp` (tolérance de 10 secondes), `iss` = `JWT_EMETTEUR`, `aud` contient `JWT_AUDIENCE`
  (`billetterie-api`, ajoutée par un mapper des clients `frontend` et `services` du realm).

## Réponses

| Cas | Statut | Code |
|---|---|---|
| Jeton valide | 200 | en-têtes `X-User-Id` (`sub`), `X-User-Roles` (rôles du realm, séparés par des virgules), `X-Client-Id` (`azp`) |
| Route publique sans jeton | 200 | aucun en-tête d'identité |
| Pas de jeton Bearer | 401 | `JETON_ABSENT` |
| Jeton expiré | 401 | `JETON_EXPIRE` |
| Signature, émetteur, audience ou clé invalides | 401 | `JETON_INVALIDE` |
| Jeton `partner` sur `/verifier`, ou jeton sans `partner` sur `/verifier/partenaires` (même sur une route publique) | 403 | `ROLE_MANQUANT` |
| Clés du realm jamais chargées (Keycloak absent) | 503 | `VERIFICATION_INDISPONIBLE` |

Traefik retire `X-User-Id`, `X-User-Roles` et `X-Client-Id` de la requête du client avant d'y
recopier ceux du vérificateur : un service peut s'y fier.

## Configuration

| Variable | Exemple |
|---|---|
| `JWT_EMETTEUR` | `http://localhost/auth/realms/billetterie` |
| `JWT_AUDIENCE` | `billetterie-api` (par défaut) |
| `JWKS_URL` | `http://keycloak:8080/auth/realms/billetterie/protocol/openid-connect/certs` |
| `ROUTES_PUBLIQUES` | `GET /api/v1/evenements,GET /api/v1/seances` |

Routes publiques : `MÉTHODE /préfixe`, séparées par des virgules. Un préfixe couvre ses
sous-chemins segment par segment (`/api/v1/evenements/42`, pas `/api/v1/evenementsX`). Un jeton
fourni sur une route publique est tout de même vérifié. Une entrée mal formée empêche le
démarrage.

## Tests

- `infra/verificateur/tests/unit` : jetons signés par une clé de test, JWKS en mémoire.
- `tests/integration/test_verification_jeton.py` : Traefik, vrai vérificateur, Keycloak et
  whoami de bout en bout.
- `tests/integration/test_partenaires_gateway.py` : hôte partenaires, quota (429) et refus de
  rôle par chaîne.
