# BIL-F27 : Front : authentification OIDC et client d'API typé

- **Branche** : `feat/bil-f27-front-auth-api`
- **Dépend de** : BIL-F26, BIL-F09
- **Service** : frontend

## Objectif

Connecter le front à Keycloak en Authorization Code + PKCE et générer un client d'API typé
depuis les contrats OpenAPI.

## Étapes

- [x] 1. Fournisseur d'authentification (oidc-client-ts) : connexion, déconnexion, renouvellement
  silencieux ; jeton gardé en mémoire.
- [x] 2. Gardes de routes par rôle (`customer`, `partner`, `admin`).
- [x] 3. Script `npm run api:gen` qui génère les types depuis `services/*/openapi.yaml` ; client
  `openapi-fetch` qui ajoute le jeton et `X-Correlation-Id`.
- [x] 4. Conversion des erreurs Problem Details en messages lisibles.
- [x] 5. Tests Vitest des gardes et de l'intercepteur.

## Critères d'acceptance

- [x] CA1 : connexion et déconnexion fonctionnent avec les utilisateurs de test
- [x] CA2 : aucun jeton n'est écrit dans localStorage ni sessionStorage
- [x] CA3 : modifier un contrat OpenAPI casse la compilation TypeScript tant que le front n'est
  pas adapté

## Contraintes

- Client Keycloak `frontend` public uniquement ; aucun secret côté navigateur.

## Décisions (validation 1)

- En-tête commun : « Se connecter », « Se déconnecter », `preferred_username` ; rappel sur
  `/connexion/rappel`, retour à la page demandée, accueil après déconnexion (`signoutRedirect`).
- Jetons en mémoire ; seul l'état temporaire de la redirection en `sessionStorage`, jamais en
  `localStorage`. Reconnexion silencieuse au rechargement ; renouvellement par jeton de
  rafraîchissement 60 s avant l'expiration, sinon « Votre session a expiré ».
- Rôles lus dans `realm_access.roles` ; garde = liste de rôles, sans hiérarchie. Sans session :
  redirection vers Keycloak ; sans le rôle : page « Accès refusé ». Aucune route de
  démonstration : gardes testées au niveau composant.
- `api:gen` : un fichier par service dans `src/api/genere/`, commité et vérifié à jour en CI ;
  `baseUrl` = origine de `urlApi()` ; `X-Correlation-Id` UUID v4 par requête ; sur 401, un
  renouvellement puis un seul rejeu.
- Problem Details convertis en `{titre, detail, code, correlationId, erreurs}`, affichés par
  `<Erreur>` (`role="alert"`) ; message générique pour toute autre erreur.
- Realm inchangé (aucun écran n'appelle l'API) ; CA3 démontré par `src/api/echos.ts`
  (`listerEchos`), cassé par un contrat modifié sous `typecheck` et `build`.
- Parcours : mots de passe lus du `.env` par une aide dans `e2e/`, sans toucher à
  `playwright.config.ts`.

## Décisions (implémentation)

- Test de la page de rappel : défaut d'isolation corrigé par `unit-test-writer` (le test attend
  la fin de son échange de code), sans retirer d'assertion.
- Playwright sur un seul worker (`workers: 1`) : les parcours partagent la plateforme et les
  comptes de test, et deux connexions simultanées déclenchent l'anti force brute de Keycloak.
- Session expirée sur une route gardée : redirection immédiate vers Keycloak.
- Validés : page `/connexion/silencieux` pour l'iframe de reconnexion ; contrats dans le filtre
  CI du job `frontend` et contrôle `git status` des types générés ; nouvel `X-Correlation-Id` au
  rejeu ; panne réseau convertie en `ErreurApi` ; retour après connexion limité aux chemins
  internes ; aucun bouton pendant le chargement ; `overrides` npm de TypeScript pour
  openapi-typescript ; formatage Prettier dans `api:gen`.
- CA3 démontré : `elements` renommé dans une copie du contrat d'echo, puis types régénérés :
  `typecheck` et `build` échouent sur `src/api/echos.ts`.

## Décisions (validation 2)

- Redirection ouverte : le retour après connexion est résolu par `new URL` et doit rester sur la
  même origine (chemins piégés testés).
- La garde affiche le message générique si la redirection vers Keycloak échoue.
- Clé React unique dans `Erreur` ; `CheminsApi` dérivé des types générés
  (`src/api/genere/index.ts`, produit par `api:gen`).
- Chemins résolus en `//…` refusés (`cheminInterne`, testée directement et exportée pour ça).
- `api:gen` : seuls les chemins `/api/` doivent être uniques entre contrats (`/health` est déclaré
  par chaque service) ; options `--contrats` et `--sortie` pour vérifier le contrôle sur des
  copies ; refus de vider un dossier de sortie qui n'est ni vide ni déjà généré.
- Troisième review : lectures immédiates du témoin `sessions` remplacées par `await waitFor(...)`
  dans `FournisseurAuthentification.test.tsx` (mêmes valeurs attendues) ; Vitest vert 10 fois de
  suite. PR ouverte sans quatrième review (code de production inchangé).
- À suivre (workflow) : `git_sur` refuse toute écriture vers un fichier nommé `openapi.yaml`, même
  hors du dépôt (copies d'essai dans le dossier temporaire).
