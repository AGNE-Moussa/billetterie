# Plan de test : BIL-F27, Front : authentification OIDC et client d'API typé

- Ticket : `docs/tickets/BIL-F27.md` ; contrat : `services/echo/openapi.yaml` (seul contrat
  existant, source des types générés et des réponses simulées)
- Niveaux : composant, parcours

Périmètre : le ticket a trois critères (CA1 à CA3) et une contrainte (client Keycloak `frontend`
public, aucun secret côté navigateur). CA3 se vérifie par une suite de commandes, sans cas de
test. Les étapes 1 à 4 portent des comportements sans critère propre (renouvellement silencieux,
gardes par rôle, intercepteur, conversion des Problem Details), repris en critères dérivés E1 à
E4, validés (réponse 19).

Le ticket ne touche ni Billets ni Commandes : aucun cas de concurrence obligatoire.

Outillage attendu :

- `composant` : Vitest, Testing Library, jsdom, rendu sous `MemoryRouter` et un
  `QueryClientProvider` de test (comme `RoutesApplication.test.tsx`). API simulée par MSW, dont
  les gestionnaires sont typés avec les types générés dans `src/api/genere/echo.ts` depuis
  `services/echo/openapi.yaml` (`EchoReponse`, `EchoPage`, `Probleme`). Deux modes (réponse 20) :
  - CA2, contrainte et configuration : vrai `UserManager` d'oidc-client-ts configuré comme
    l'application, Keycloak simulé par MSW sur la découverte OIDC
    (`/auth/realms/billetterie/.well-known/openid-configuration`), le point de jeton et le point
    de fin de session ;
  - gardes et écrans : `UserManager` injecté dans le fournisseur, état de session imposé par le
    test.
  MSW, oidc-client-ts, openapi-typescript et openapi-fetch ne sont pas encore dans
  `frontend/package.json` : à ajouter par l'implémentation.
- `parcours` : Playwright, `baseURL` `http://localhost`, Chromium seul, contre `make up` (décision
  BIL-F26), vrai Keycloak et vrais utilisateurs de test du realm `billetterie` (realm inchangé,
  réponse 16). `frontend/playwright.config.ts` reste inchangé (verrouillé) ; les mots de passe sont
  lus dans le `.env` racine par une aide de `frontend/e2e/` (`process.loadEnvFile`). Sur la page
  Keycloak, champs trouvés par libellé (`getByLabel`) et bouton par rôle (`getByRole`). Parcours
  limités à la connexion et à la déconnexion depuis l'accueil (réponse 9).
- Dans Vitest et Playwright, le nom du cas sert de libellé du `it(...)` / `test(...)`.

Données synthétiques :

- Utilisateurs du realm (`infra/keycloak/realm-billetterie.json`) : `client.test`
  (`client.test@exemple.test`, rôle `customer`), `partenaire.test`
  (`partenaire.test@exemple.test`, rôle `partner`), `admin.test` (`admin.test@exemple.test`, rôle
  `admin`). Mots de passe lus dans `KEYCLOAK_MDP_CLIENT`, `KEYCLOAK_MDP_PARTENAIRE`,
  `KEYCLOAK_MDP_ADMIN` du `.env` (jamais écrits dans un test).
- Jetons simulés : JWT non signés fabriqués par le test (le front les décode sans vérifier la
  signature), `iss` `<origine>/auth/realms/billetterie`, `aud` `billetterie-api`, `azp`
  `frontend`, `preferred_username` selon le cas, `realm_access.roles` selon le cas, `sub` = UUID
  généré (`crypto.randomUUID()`) ; chaînes repérables (`jeton-acces-de-test-<uuid>`,
  `jeton-rafraichissement-de-test-<uuid>`, `jeton-identite-de-test-<uuid>`) pour la recherche
  dans le stockage et la console. Aucun vrai jeton ni secret.
- Identifiants de corrélation : UUID générés.
- `<origine>` : `window.location.origin` de jsdom en composant, `http://localhost` en parcours.

Commandes (PowerShell, depuis `frontend/` sauf mention) : `curl.exe` plutôt que l'alias `curl`.

## Questions

Réponses du développeur (validation 1) :

1. En-tête commun à toutes les pages : boutons « Se connecter » et « Se déconnecter » ; connecté,
   il affiche le `preferred_username` ; pendant la finalisation : « Connexion en cours… ».
2. `redirect_uri` = `/connexion/rappel` ; après connexion, retour à la page demandée ;
   `post_logout_redirect_uri` = accueil ; autorité = `window.location.origin` + `urlKeycloak()` +
   `/realms/billetterie`.
3. Déconnexion par `signoutRedirect` (session Keycloak fermée).
4. Utilisateur (jetons) en mémoire (`InMemoryWebStorage`) ; état temporaire (`state`,
   `code_verifier`) en `sessionStorage`, jamais en `localStorage`. CA2 vérifie qu'aucun jeton
   d'accès, de rafraîchissement ni d'identité n'est dans `localStorage` ni `sessionStorage`.
5. Au rechargement : reconnexion silencieuse (`signinSilent`, même domaine que Keycloak).
6. Renouvellement par jeton de rafraîchissement (en mémoire), 60 s avant l'expiration ; en cas
   d'échec : état non connecté et message « Votre session a expiré ».
7. Rôles lus dans `realm_access.roles` du jeton d'accès, décodé sans vérification de signature ;
   une garde accepte une liste de rôles ; aucune hiérarchie : `admin` ne passe que les gardes qui
   le listent.
8. Sans session : redirection vers Keycloak (retour à la page demandée) ; connecté sans le rôle :
   page « Accès refusé » (h1 et lien vers l'accueil) ; pendant le chargement de la session :
   « Chargement de la session… » avec `role="status"`.
9. Aucune route de démonstration dans l'application : gardes testées au niveau composant
   seulement ; parcours limités à la connexion et à la déconnexion depuis l'accueil.
10. `npm run api:gen` génère un fichier par `services/*/openapi.yaml` dans
    `src/api/genere/<service>.ts`, commité ; la CI vérifie qu'il est à jour (`api:gen` puis
    `git diff --exit-code`).
11. `baseUrl` du client = origine de `urlApi()` (les chemins du contrat commencent par
    `/api/v1`) ; un seul module client `src/api/client.ts`.
12. `X-Correlation-Id` : UUID v4 par requête ; l'identifiant renvoyé par la réponse est conservé
    dans l'erreur convertie.
13. Sans session, la requête part sans `Authorization` ; sur 401 : un renouvellement silencieux
    puis un seul rejeu, sinon l'erreur.
14. Conversion en `{titre, detail, code, correlationId, erreurs}` ; composant `<Erreur probleme>`
    (`role="alert"`) livré : titre, détail, liste des `erreurs` (REQUETE_INVALIDE),
    « Référence : <correlationId> » ; pas de message propre à un code.
15. Erreur qui n'est pas un Problem Details (HTML, corps vide, panne réseau, rappel OIDC en
    erreur) : « Le service est momentanément indisponible. Réessayez dans quelques instants. »
16. Realm inchangé : aucun écran n'appelle l'API dans ce ticket.
17. Les parcours lisent les mots de passe du `.env` racine par une aide dans `frontend/e2e/`
    (`process.loadEnvFile`), sans modifier `playwright.config.ts` (verrouillé) ; page Keycloak :
    sélection par libellé et rôle.
18. CA3 : un module typé `src/api/echos.ts` (fonction `listerEchos`) consomme les types d'echo ;
    « la compilation » = `npm run typecheck` et `npm run build` ; renommer un champ du contrat
    echo puis `api:gen` doit les casser.
19. Critères dérivés E1 à E4 validés.
20. Vrai `UserManager` avec MSW pour CA2 et la configuration ; `UserManager` injectable dans le
    fournisseur pour les gardes et les écrans.

Plus aucune question ouverte : plan validé.

## CA1 : connexion et déconnexion fonctionnent avec les utilisateurs de test

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_sans_session_l_en_tete_propose_de_se_connecter` | composant | fournisseur sans utilisateur (`UserManager` injecté), accueil sous `MemoryRouter` | bouton « Se connecter » trouvé par `getByRole("button")` dans l'en-tête ; aucun bouton « Se déconnecter », aucun nom d'utilisateur (état vide) |
| `test_se_connecter_redirige_vers_keycloak_en_code_avec_pkce_s256` | composant | vrai `UserManager`, MSW sur la découverte OIDC ; navigation (`window.location.assign`) interceptée ; clic sur « Se connecter » | une seule redirection vers `<origine>/auth/realms/billetterie/protocol/openid-connect/auth` (autorité = origine + `urlKeycloak()` + `/realms/billetterie`) avec `client_id=frontend`, `response_type=code`, `code_challenge_method=S256`, `code_challenge` non vide, `state` non vide, `redirect_uri=<origine>/connexion/rappel` ; aucun `response_type=token` |
| `test_la_page_de_rappel_annonce_la_connexion_en_cours` | composant | route `/connexion/rappel?code=<uuid>&state=<state connu>`, point de jeton MSW retardé | texte « Connexion en cours… » affiché ; aucune page de destination rendue tant que le jeton n'est pas reçu (état chargement) |
| `test_la_page_de_rappel_echange_le_code_et_ramene_a_la_page_demandee` | composant | connexion lancée depuis `/page-de-test` (route de test sous `MemoryRouter`), rappel avec `code` et `state` ; point de jeton MSW : jeton d'accès `customer` synthétique, `preferred_username` = `client.test` | utilisateur connecté ; la page affichée est `/page-de-test` ; `code` et `state` ne restent pas dans l'URL ; l'en-tête affiche `client.test` (état succès) |
| `test_un_rappel_en_erreur_affiche_le_message_generique` (paramétré : `?error=access_denied&state=<state connu>` ; point de jeton MSW répondant 400 `invalid_grant`) | composant | route `/connexion/rappel` avec les données du paramètre | message « Le service est momentanément indisponible. Réessayez dans quelques instants. » affiché ; utilisateur non connecté, « Se connecter » de nouveau proposé dans l'en-tête ; aucune exception non gérée (état erreur) |
| `test_connecte_l_en_tete_affiche_le_nom_d_utilisateur_et_propose_de_se_deconnecter` | composant | fournisseur avec un utilisateur synthétique, `preferred_username` = `client.test` | `client.test` affiché dans l'en-tête ; bouton « Se déconnecter » présent ; « Se connecter » absent (état succès) |
| `test_se_deconnecter_oublie_l_utilisateur_et_ferme_la_session_keycloak` | composant | vrai `UserManager`, utilisateur connecté (jeton d'identité `jeton-identite-de-test-<uuid>`), MSW sur la découverte ; navigation interceptée ; clic sur « Se déconnecter » | utilisateur retiré du fournisseur ; une redirection (`signoutRedirect`) vers `<origine>/auth/realms/billetterie/protocol/openid-connect/logout` avec `id_token_hint` = le jeton d'identité synthétique et `post_logout_redirect_uri=<origine>/` |
| `test_chaque_utilisateur_de_test_se_connecte_puis_se_deconnecte_depuis_l_accueil` (paramétré `client.test`, `partenaire.test`, `admin.test`) | parcours | `make up` ; `page.goto("/")`, « Se connecter », saisie sur la page Keycloak (champs par libellé, bouton par rôle, mot de passe lu dans le `.env` par l'aide de `frontend/e2e/`), puis « Se déconnecter » | après connexion : retour sur `http://localhost/`, l'en-tête affiche le `preferred_username` de l'utilisateur ; après déconnexion : retour sur l'accueil, « Se connecter » de nouveau visible ; un nouveau clic sur « Se connecter » réaffiche le formulaire Keycloak (session fermée) |

## CA2 : aucun jeton n'est écrit dans localStorage ni sessionStorage

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_apres_connexion_aucun_jeton_n_est_dans_le_stockage_du_navigateur` | composant | vrai `UserManager` configuré comme l'application ; connexion complète simulée (redirection interceptée, rappel, point de jeton MSW renvoyant `jeton-acces-de-test-<uuid>`, `jeton-rafraichissement-de-test-<uuid>`, `jeton-identite-de-test-<uuid>`) | aucune valeur de `localStorage` ni de `sessionStorage` ne contient l'un des trois jetons ; `document.cookie` ne les contient pas ; le jeton d'accès reste disponible pour le client d'API (en mémoire) |
| `test_l_etat_temporaire_de_connexion_va_en_session_storage_jamais_en_local_storage` | composant | vrai `UserManager`, clic sur « Se connecter », redirection interceptée (avant le rappel) | `localStorage` vide de toute clé `oidc.*` ; l'état de connexion (`state`, `code_verifier`) est dans `sessionStorage` ; aucun jeton dans l'un ou l'autre |
| `test_apres_renouvellement_aucun_jeton_n_est_dans_le_stockage_du_navigateur` | composant | utilisateur connecté comme ci-dessus, renouvellement par jeton de rafraîchissement déclenché (minuteries simulées, 60 s avant `exp`), point de jeton MSW renvoyant de nouveaux jetons synthétiques | ni les anciens ni les nouveaux jetons dans `localStorage`, `sessionStorage` ou `document.cookie` |
| `test_apres_une_vraie_connexion_aucun_jeton_n_est_dans_le_stockage_du_navigateur` | parcours | `make up`, connexion de `client.test` depuis l'accueil ; réponse du point de jeton capturée (`page.waitForResponse` sur `/auth/realms/billetterie/protocol/openid-connect/token`) | `page.evaluate` sur `localStorage`, `sessionStorage` et `document.cookie` : aucune valeur ne contient `access_token`, `refresh_token` ni `id_token` de la réponse capturée |

## CA3 : modifier un contrat OpenAPI casse la compilation TypeScript tant que le front n'est pas adapté

Critère d'outillage : vérifié par commandes, sans cas de test. `<compilation>` désigne
`npm run typecheck` puis `npm run build` ; les deux doivent réussir (base verte) et les deux
doivent échouer (contrat modifié). Le code consommateur est `listerEchos` de `src/api/echos.ts` :
il doit lire le champ renommé à l'étape 3 (ou le nommer dans son type de retour) pour que le
renommage le casse.

| Étape | Commande | Attendu |
|---|---|---|
| 1. Point de départ | `npm run api:gen`, puis `git diff --exit-code -- src/api/genere` | génération sans erreur ; `src/api/genere/echo.ts` identique au fichier commité (code de sortie 0) ; même vérification en CI |
| 2. Base verte | `<compilation>` | code de sortie 0 pour les deux commandes |
| 3. Champ renommé | dans `services/echo/openapi.yaml`, renommer la propriété requise `elements` de `EchoPage` en `elements_trouves` ; `npm run api:gen` ; `<compilation>` | code de sortie non nul pour `typecheck` et pour `build` ; erreur `TS` dans `src/api/echos.ts` (et, sous `typecheck`, dans les gestionnaires MSW typés) |
| 4. Chemin renommé | restaurer, puis renommer le chemin `/api/v1/echos` en `/api/v1/echos-liste` ; `npm run api:gen` ; `<compilation>` | code de sortie non nul ; erreur `TS` sur l'appel `client.GET("/api/v1/echos", ...)` de `listerEchos` (chemin inconnu) |
| 5. Retour | `git checkout -- services/echo/openapi.yaml` ; `npm run api:gen` ; `<compilation>` | code de sortie 0 ; `git status` propre |
| 6. Contrôle CI | sur une branche de test, modifier le contrat sans relancer `api:gen` | l'étape CI `api:gen` + `git diff --exit-code` échoue |
| 7. Pas de client écrit à la main | `Select-String -Path src\**\*.ts,src\**\*.tsx -Pattern 'fetch\(' -Exclude *.test.*` (hors `src/api/genere/` et `src/api/client.ts`) | aucun `fetch` direct vers une URL d'API (rule `frontend.md`) |

## Contrainte : client Keycloak `frontend` public uniquement, aucun secret côté navigateur

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_les_requetes_au_point_de_jeton_n_envoient_aucun_secret_client` (paramétré : échange du code ; renouvellement par jeton de rafraîchissement) | composant | vrai `UserManager`, connexion puis renouvellement simulés ; le gestionnaire MSW du point de jeton capture chaque requête | corps `application/x-www-form-urlencoded` avec `client_id=frontend` ; échange : `grant_type=authorization_code`, `code_verifier` de 43 à 128 caractères ; renouvellement : `grant_type=refresh_token` ; aucun champ `client_secret` ; aucun en-tête `Authorization` |

Vérification par commandes :

| Commande | Attendu |
|---|---|
| `npm run build`, puis `Select-String -Path dist\assets\*.js -Pattern 'client_secret','KEYCLOAK_SERVICES_SECRET'` | aucune occurrence |
| `Select-String -Path ..\.env.example -Pattern '^VITE_.*SECRET'` | aucune variable de secret exposée au front |

## E1 : fournisseur d'authentification, renouvellement silencieux (étape 1, dérivé)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_le_jeton_est_renouvele_par_jeton_de_rafraichissement_60_s_avant_son_expiration` | composant | vrai `UserManager`, utilisateur connecté, jeton d'accès `exp` = maintenant + 300 s, minuteries simulées ; point de jeton MSW (`grant_type=refresh_token`) | aucune requête de renouvellement avant `exp` − 60 s ; une requête `grant_type=refresh_token` portant le jeton de rafraîchissement en mémoire à `exp` − 60 s ; aucune redirection de la page ; le fournisseur expose le nouveau jeton ; l'utilisateur reste connecté |
| `test_un_echec_du_renouvellement_ramene_a_l_etat_non_connecte_avec_session_expiree` | composant | point de jeton MSW répondant 400 `invalid_grant` au renouvellement | utilisateur retiré ; message « Votre session a expiré » affiché ; « Se connecter » de nouveau proposé dans l'en-tête ; aucune exception non gérée |
| `test_au_demarrage_la_session_keycloak_existante_est_retrouvee_sans_saisie` | composant | démarrage du fournisseur sans utilisateur en mémoire ; `UserManager` injecté dont `signinSilent` réussit avec un utilisateur `client.test` synthétique | `signinSilent` appelé une fois au démarrage ; utilisateur connecté sans redirection pleine page ; l'en-tête affiche `client.test` |
| `test_au_demarrage_sans_session_keycloak_l_application_reste_non_connectee` | composant | démarrage du fournisseur sans utilisateur ; `signinSilent` injecté qui échoue (`login_required`) | état non connecté ; « Se connecter » proposé ; aucune redirection pleine page ; aucune exception non gérée |

## E2 : gardes de routes par rôle `customer`, `partner`, `admin` (étape 2, dérivé)

Routes protégées déclarées par le test sous `MemoryRouter` (aucune route de démonstration dans
l'application) ; `UserManager` injecté.

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_une_route_protegee_sans_session_redirige_vers_keycloak_avec_retour_a_la_page_demandee` | composant | route `/page-protegee` gardée, fournisseur sans utilisateur | `signinRedirect` appelé une fois, avec `/page-protegee` comme page de retour ; contenu protégé absent (état vide) |
| `test_pendant_le_chargement_de_la_session_la_garde_affiche_chargement_de_la_session` | composant | fournisseur en cours de chargement (`signinSilent` en attente) | « Chargement de la session… » dans un élément `role="status"` ; ni le contenu protégé, ni « Accès refusé », ni redirection (état chargement) |
| `test_chaque_garde_n_admet_que_les_roles_qu_elle_liste` (paramétré : rôles `customer`, `partner`, `admin` × gardes `["customer"]`, `["partner"]`, `["admin"]`) | composant | jeton d'accès synthétique non signé avec `realm_access.roles` = `[<rôle>]` | contenu protégé rendu seulement quand le rôle est listé ; « Accès refusé » sinon, y compris pour `admin` sur les gardes `["customer"]` et `["partner"]` (aucune hiérarchie) |
| `test_une_garde_a_plusieurs_roles_admet_chacun_d_eux` | composant | garde `["partner", "admin"]` ; jetons `realm_access.roles` = `["partner"]`, `["admin"]`, `["customer"]` | admis pour `partner` et `admin` ; « Accès refusé » pour `customer` |
| `test_un_role_refuse_affiche_acces_refuse_sans_la_page_protegee` | composant | utilisateur `client.test` synthétique (`customer`) sur une route gardée `["admin"]` | h1 « Accès refusé » (`getByRole("heading", { level: 1 })`) et un lien vers l'accueil (`getByRole("link")`, `href` = `/`) ; aucun texte du contenu protégé dans le DOM ; aucune redirection vers Keycloak (état erreur) |
| `test_un_jeton_sans_role_du_realm_est_refuse_par_toutes_les_gardes` (paramétré : sans `realm_access` ; `realm_access.roles` = `[]`) | composant | jeton d'accès synthétique correspondant | les gardes `["customer"]`, `["partner"]`, `["admin"]` affichent « Accès refusé » ; aucune exception |
| `test_les_roles_sont_lus_dans_le_jeton_d_acces` | composant | jeton d'accès `realm_access.roles` = `["customer"]`, profil d'identité portant `realm_access.roles` = `["admin"]` | la garde `["admin"]` refuse, la garde `["customer"]` admet |

## E3 : client typé généré, jeton et `X-Correlation-Id` ajoutés (étape 3, dérivé)

Client unique `src/api/client.ts` (openapi-fetch, types de `src/api/genere/echo.ts`). Les
réponses simulées suivent `services/echo/openapi.yaml` : `GET /api/v1/echos/{message}` →
`EchoReponse` (`message`, `instance`, `cree_le` en ISO 8601 avec fuseau) ; `GET /api/v1/echos` →
`EchoPage` (`elements`, `page`, `size`, `total`).

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_lister_echos_rend_la_page_typee_du_contrat` | composant | `listerEchos` (`src/api/echos.ts`) avec `page=1`, `size=20` ; MSW renvoie un `EchoPage` de deux `EchoReponse` synthétiques | requête `GET <origine>/api/v1/echos?page=1&size=20` ; valeur rendue égale au corps simulé (`elements`, `page`, `size`, `total`) |
| `test_le_client_ajoute_le_jeton_d_acces_en_bearer` | composant | utilisateur connecté avec `jeton-acces-de-test-<uuid>` ; `GET /api/v1/echos/{message}` avec `message` = `bonjour`, MSW renvoie un `EchoReponse` | la requête capturée porte `Authorization: Bearer jeton-acces-de-test-<uuid>` ; la réponse typée est rendue au code appelant |
| `test_le_client_ajoute_un_x_correlation_id_uuid_v4` | composant | même appel | en-tête `X-Correlation-Id` présent, UUID v4 (`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`), donc conforme à `FORMAT_VALIDE` de `commun.correlation` |
| `test_deux_requetes_portent_des_x_correlation_id_differents` | composant | deux appels `listerEchos` successifs | deux identifiants UUID v4 distincts |
| `test_le_client_appelle_le_chemin_du_contrat_sur_l_origine_de_l_url_d_api` (paramétré : `VITE_API_URL` absente, donc `urlApi()` = `/api` ; `VITE_API_URL` = `http://api.exemple.test/api` par `vi.stubEnv`) | composant | appel `listerEchos` `page=1`, `size=20` | URL capturée par MSW : `<origine>/api/v1/echos?page=1&size=20`, puis `http://api.exemple.test/api/v1/echos?page=1&size=20` ; jamais `/api/api/v1/...` |
| `test_sans_session_la_requete_part_sans_en_tete_authorization` | composant | aucun utilisateur ; appel `listerEchos` | la requête est émise ; aucun en-tête `Authorization` (ni `Bearer undefined`) ; `X-Correlation-Id` présent |
| `test_apres_renouvellement_le_client_envoie_le_nouveau_jeton` | composant | jeton renouvelé (comme E1), puis un appel | `Authorization` porte le nouveau jeton, plus l'ancien |
| `test_apres_deconnexion_le_client_n_envoie_plus_l_ancien_jeton` | composant | connexion, déconnexion, puis un appel | requête sans `Authorization` ; aucun en-tête ne contient l'ancien jeton |
| `test_une_reponse_401_declenche_un_renouvellement_puis_un_seul_rejeu` | composant | MSW répond 401 `application/problem+json` (`code` = `JETON_EXPIRE`) au premier appel, 200 `EchoPage` au second ; renouvellement silencieux réussi | une requête au point de jeton entre les deux ; exactement deux requêtes vers l'API, la seconde avec le nouveau jeton ; la réponse 200 est rendue au code appelant |
| `test_un_401_apres_le_rejeu_rend_l_erreur_sans_autre_tentative` | composant | MSW répond 401 `JETON_EXPIRE` à chaque appel ; renouvellement réussi | exactement deux requêtes vers l'API et un seul renouvellement ; erreur convertie (E4) avec `code` = `JETON_EXPIRE` ; aucune boucle |
| `test_un_echec_du_renouvellement_apres_401_rend_l_erreur_sans_rejeu` | composant | MSW répond 401 `JETON_EXPIRE` ; point de jeton 400 `invalid_grant` | une seule requête vers l'API ; erreur rendue au code appelant ; état non connecté avec « Votre session a expiré » (comme E1) |
| `test_aucun_jeton_n_apparait_dans_la_console` | composant | `console.log`, `info`, `warn`, `error`, `debug` espionnés pendant un appel réussi, un 401 rejoué et un échec de renouvellement | aucun argument journalisé ne contient le jeton d'accès, de rafraîchissement ou d'identité (rule `securite.md`) |

## E4 : conversion des erreurs Problem Details en messages lisibles (étape 4, dérivé)

Corps simulés conformes au schéma `Probleme` du contrat (`type`, `title`, `status`, `detail`,
`code` requis sauf `type` ; `correlation_id` et `erreurs` facultatifs), en
`application/problem+json`. Forme convertie : `{titre, detail, code, correlationId, erreurs}`.

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_un_probleme_est_converti_en_titre_detail_code_correlation_et_erreurs` | composant | `GET /api/v1/echos/{message}` → 404 `{"title": "Not Found", "status": 404, "detail": "Aucun echo pour ce message.", "code": "ECHO_INTROUVABLE", "correlation_id": "<uuid>"}`, en-tête `X-Correlation-Id` = le même `<uuid>` | valeur convertie : `titre` = `Not Found`, `detail` = `Aucun echo pour ce message.`, `code` = `ECHO_INTROUVABLE`, `correlationId` = `<uuid>`, `erreurs` vide ou absent ; la décision se prend sur `code`, sans analyse du texte (rule `frontend.md`) |
| `test_l_identifiant_de_correlation_renvoye_par_la_reponse_est_conserve_dans_l_erreur` | composant | requête émise avec `X-Correlation-Id` = `<uuid-A>` ; MSW répond 404 Problem Details sans `correlation_id` dans le corps, en-tête de réponse `X-Correlation-Id` = `<uuid-B>` | `correlationId` de l'erreur convertie = `<uuid-B>` (celui de la réponse) |
| `test_le_composant_d_erreur_annonce_le_titre_le_detail_et_la_reference_en_alerte` | composant | `<Erreur probleme>` rendu avec le problème 404 converti | conteneur `role="alert"` contenant `Not Found`, `Aucun echo pour ce message.` et « Référence : <uuid> » ; aucune trace technique |
| `test_le_composant_d_erreur_liste_les_erreurs_d_une_requete_invalide` | composant | `listerEchos` `page=0` → 422 `code` = `REQUETE_INVALIDE`, `erreurs` = `[{"champ": "query.page", "message": "doit être supérieur ou égal à 1"}]`, converti puis rendu par `<Erreur probleme>` | `erreurs` conservées dans la valeur convertie ; liste (`getByRole("list")`) avec un élément contenant `query.page` et son message, dans le conteneur `role="alert"` |
| `test_le_message_affiche_est_celui_du_serveur_quel_que_soit_le_code` (paramétré : 401 `JETON_EXPIRE`, 403 `SCOPE_MANQUANT`, 403 `ROLE_MANQUANT`) | composant | Problem Details synthétique avec `title` et `detail` propres au cas, rendu par `<Erreur probleme>` | le texte affiché est exactement `title` et `detail` du serveur ; aucun message propre au code |
| `test_une_erreur_qui_n_est_pas_un_probleme_donne_le_message_generique` (paramétré : 502 `text/html` de Traefik ; 500 au corps vide ; 429 au corps vide) | composant | réponses MSW correspondantes, rendues par `<Erreur probleme>` | « Le service est momentanément indisponible. Réessayez dans quelques instants. » ; aucune exception de lecture JSON remontée à l'écran |
| `test_une_panne_reseau_donne_le_message_generique` | composant | MSW `HttpResponse.error()` | « Le service est momentanément indisponible. Réessayez dans quelques instants. » ; aucune exception non gérée |

## Couverture

| Critère | Cas |
|---|---|
| CA1 | `test_sans_session_l_en_tete_propose_de_se_connecter`, `test_se_connecter_redirige_vers_keycloak_en_code_avec_pkce_s256`, `test_la_page_de_rappel_annonce_la_connexion_en_cours`, `test_la_page_de_rappel_echange_le_code_et_ramene_a_la_page_demandee`, `test_un_rappel_en_erreur_affiche_le_message_generique`, `test_connecte_l_en_tete_affiche_le_nom_d_utilisateur_et_propose_de_se_deconnecter`, `test_se_deconnecter_oublie_l_utilisateur_et_ferme_la_session_keycloak`, `test_chaque_utilisateur_de_test_se_connecte_puis_se_deconnecte_depuis_l_accueil` |
| CA2 | `test_apres_connexion_aucun_jeton_n_est_dans_le_stockage_du_navigateur`, `test_l_etat_temporaire_de_connexion_va_en_session_storage_jamais_en_local_storage`, `test_apres_renouvellement_aucun_jeton_n_est_dans_le_stockage_du_navigateur`, `test_apres_une_vraie_connexion_aucun_jeton_n_est_dans_le_stockage_du_navigateur` |
| CA3 | aucun cas : commandes `api:gen`, `git diff --exit-code`, `npm run typecheck`, `npm run build`, modification et restauration de `services/echo/openapi.yaml`, recherche de `fetch(` ; voir aussi `test_lister_echos_rend_la_page_typee_du_contrat` |
| Contrainte | `test_les_requetes_au_point_de_jeton_n_envoient_aucun_secret_client` ; commandes `npm run build` et `Select-String` ; voir aussi `test_se_connecter_redirige_vers_keycloak_en_code_avec_pkce_s256` |
| E1 | `test_le_jeton_est_renouvele_par_jeton_de_rafraichissement_60_s_avant_son_expiration`, `test_un_echec_du_renouvellement_ramene_a_l_etat_non_connecte_avec_session_expiree`, `test_au_demarrage_la_session_keycloak_existante_est_retrouvee_sans_saisie`, `test_au_demarrage_sans_session_keycloak_l_application_reste_non_connectee` |
| E2 | `test_une_route_protegee_sans_session_redirige_vers_keycloak_avec_retour_a_la_page_demandee`, `test_pendant_le_chargement_de_la_session_la_garde_affiche_chargement_de_la_session`, `test_chaque_garde_n_admet_que_les_roles_qu_elle_liste`, `test_une_garde_a_plusieurs_roles_admet_chacun_d_eux`, `test_un_role_refuse_affiche_acces_refuse_sans_la_page_protegee`, `test_un_jeton_sans_role_du_realm_est_refuse_par_toutes_les_gardes`, `test_les_roles_sont_lus_dans_le_jeton_d_acces` |
| E3 | `test_lister_echos_rend_la_page_typee_du_contrat`, `test_le_client_ajoute_le_jeton_d_acces_en_bearer`, `test_le_client_ajoute_un_x_correlation_id_uuid_v4`, `test_deux_requetes_portent_des_x_correlation_id_differents`, `test_le_client_appelle_le_chemin_du_contrat_sur_l_origine_de_l_url_d_api`, `test_sans_session_la_requete_part_sans_en_tete_authorization`, `test_apres_renouvellement_le_client_envoie_le_nouveau_jeton`, `test_apres_deconnexion_le_client_n_envoie_plus_l_ancien_jeton`, `test_une_reponse_401_declenche_un_renouvellement_puis_un_seul_rejeu`, `test_un_401_apres_le_rejeu_rend_l_erreur_sans_autre_tentative`, `test_un_echec_du_renouvellement_apres_401_rend_l_erreur_sans_rejeu`, `test_aucun_jeton_n_apparait_dans_la_console` |
| E4 | `test_un_probleme_est_converti_en_titre_detail_code_correlation_et_erreurs`, `test_l_identifiant_de_correlation_renvoye_par_la_reponse_est_conserve_dans_l_erreur`, `test_le_composant_d_erreur_annonce_le_titre_le_detail_et_la_reference_en_alerte`, `test_le_composant_d_erreur_liste_les_erreurs_d_une_requete_invalide`, `test_le_message_affiche_est_celui_du_serveur_quel_que_soit_le_code`, `test_une_erreur_qui_n_est_pas_un_probleme_donne_le_message_generique`, `test_une_panne_reseau_donne_le_message_generique` |

États d'écran (composant) : chargement (`test_la_page_de_rappel_annonce_la_connexion_en_cours`,
`test_pendant_le_chargement_de_la_session_la_garde_affiche_chargement_de_la_session`), vide
(`test_sans_session_l_en_tete_propose_de_se_connecter`,
`test_une_route_protegee_sans_session_redirige_vers_keycloak_avec_retour_a_la_page_demandee`),
erreur (`test_un_rappel_en_erreur_affiche_le_message_generique`,
`test_un_role_refuse_affiche_acces_refuse_sans_la_page_protegee`,
`test_le_composant_d_erreur_annonce_le_titre_le_detail_et_la_reference_en_alerte`), succès
(`test_connecte_l_en_tete_affiche_le_nom_d_utilisateur_et_propose_de_se_deconnecter`,
`test_la_page_de_rappel_echange_le_code_et_ramene_a_la_page_demandee`).

Parcours : un seul par critère (CA1 et CA2) ; les parcours E1 (rechargement), E2 (route admin) et
E3 (écran appelant l'API) sont retirés (réponses 9 et 16).
