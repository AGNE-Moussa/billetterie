# Plan de test : BIL-F28, Front : composants de base et mise en page

- Ticket : `docs/tickets/BIL-F28.md` ; contrat : aucun (aucun composant n'appelle l'API ; les
  formes `{elements, page, size, total}` et Problem Details viennent de `docs/conventions.md` et
  du `<Erreur>` livré par BIL-F27)
- Niveaux : composant, parcours

Périmètre : deux critères (CA1, CA2) et une contrainte (aucune logique métier, aucun appel d'API
dans les composants). CA1 (« chaque composant a au moins un test ») est découpé par composant
livré aux étapes 1 à 4 : mise en page, bouton, champ de formulaire, tableau paginé, carte,
dialogue de confirmation, notification, états chargement / vide / erreur, thème. Les exigences
d'accessibilité (WAI-ARIA Authoring Practices : formulaires, dialogues, tableaux) sont vérifiées
dans les cas de chaque composant. Le ticket ne touche ni Billets ni Commandes : aucun cas de
concurrence obligatoire.

Existant réutilisé, à étendre et non à dupliquer :

- `src/composants/EnTete.tsx` (BIL-F27) : « Se connecter » / « Se déconnecter », nom
  d'utilisateur, « Votre session a expiré ». Il devient l'en-tête de la mise en page ; ses cas
  BIL-F27 (`test_sans_session_l_en_tete_propose_de_se_connecter`,
  `test_connecte_l_en_tete_affiche_le_nom_d_utilisateur_et_propose_de_se_deconnecter`, etc.)
  et le parcours `e2e/connexion.spec.ts` doivent rester verts sans modification de leurs
  attentes.
- `src/composants/Erreur.tsx` et `Erreur.test.tsx` (BIL-F27) : c'est l'état commun « erreur »
  (titre, détail, erreurs de champ, « Référence : <correlationId> », `role="alert"`). Ses cinq
  cas existants comptent pour CA1 ; un seul cas est ajouté ici (absence de référence).
- `src/auth/session.ts` (`useSession`, statuts `chargement` / `connecte` / `non-connecte`,
  `roles`) : la navigation lit les rôles par ce hook ; les tests imposent la session par
  `ContexteSession.Provider` (pas de `UserManager`, pas de Keycloak simulé).
- `RoutesApplication.tsx` : la mise en page y remplace l'`<EnTete />` posé seul ;
  `test_la_route_racine_affiche_la_page_d_accueil` et
  `test_une_route_inconnue_affiche_la_page_introuvable` restent verts.

Outillage attendu :

- `composant` : Vitest, Testing Library (`@testing-library/react`, `user-event` pour le clavier
  : `user.tab()`, `user.keyboard("{Enter}")`, `"{ }"`, `"{Escape}"`, `"{Shift>}{Tab}{/Shift}"`),
  `jest-dom` (`toHaveAccessibleName`, `toHaveAccessibleDescription`, `toHaveFocus`,
  `toHaveAttribute`), jsdom, rendu sous `MemoryRouter` quand le composant contient un lien.
  MSW reste actif (`onUnhandledFrame: "error"` dans `setupTests.ts`) : toute requête émise par
  un composant fait échouer le test, ce qui sert la contrainte. `window.matchMedia` simulé par
  le test pour le thème ; minuteries simulées (`vi.useFakeTimers`) pour les notifications.
  Sélection par rôle et nom accessible d'abord (`getByRole`, `getByLabelText`), jamais par
  classe CSS.
- `parcours` : Playwright, `baseURL` `http://localhost`, Chromium seul, contre `make up`
  (décision BIL-F26), aide `e2e/utilisateursDeTest.ts` (BIL-F27) pour la connexion ;
  `playwright.config.ts` inchangé (verrouillé). Un seul parcours, pour CA2.
- Dans Vitest et Playwright, le nom du cas sert de libellé du `it(...)` / `test(...)`.

Données synthétiques :

- Session imposée : `nomUtilisateur` = `client.test`, `partenaire.test` ou `admin.test`,
  `roles` = `["customer"]`, `["partner"]` ou `["admin"]` ; aucun jeton nécessaire.
- Liens de navigation de test (si la configuration est injectable, voir Q1) : libellés et
  chemins fictifs (`Lien client de test` → `/espace-client-test`, `Lien partenaire de test` →
  `/espace-partenaire-test`, `Lien admin de test` → `/espace-admin-test`).
- Lignes de tableau : objets `{id: crypto.randomUUID(), libelle: "Élément de test <n>",
  montant_centimes: <entier>}` ; page simulée `{elements, page, size, total}` (`page` ≥ 1,
  `size` 20 par défaut, conventions).
- Champ : libellé « Adresse e-mail », valeur `client.test@exemple.test`, message d'erreur
  synthétique « Adresse e-mail de test invalide ».
- Erreur : problème converti synthétique, `correlationId` = UUID généré.
- Parcours : `client.test` du realm, mot de passe lu dans `.env` par l'aide existante.

## Questions

**Réponses du développeur (validation 1, 2026-10-24)** : toutes les recommandations ci-dessous
sont retenues telles quelles (questions 1 à 19). Le plan est validé.

**Précisions après le squelette (développeur, 2026-10-24)** :

- `PageAccueil.test.tsx` (BIL-F26) : le test est adapté pour rendre la page sous `MiseEnPage` et
  vérifier le `main` unique (même intention) ; les pages n'ont plus de `<main>`.
- `FournisseurTheme` et `FournisseurNotifications` sont posés dans `main.tsx`, hors de
  `MiseEnPage` ; les tests enveloppent eux-mêmes leur rendu dans les fournisseurs utiles.
- Lien de navigation : sans `roles`, public ; `roles: []`, visible par personne (comme
  `GardeRoles`).
- Bouchon de `HTMLDialogElement.showModal` / `close` (absents de jsdom) écrit par
  `unit-test-writer` dans `setupTests.ts`.
- Types de champ `select` et `textarea` inclus (question 11).

1. **Liens de navigation par rôle sans écran métier.** Aucun écran métier n'existe ; quels liens
   la navigation affiche-t-elle pour `customer`, `partner`, `admin` ? Recommandation : un
   composant `Navigation` piloté par une configuration `{libelle, chemin, roles}[]` injectable
   (prop ou module `src/navigation.ts`) ; l'application ne livre que « Accueil » (public) tant
   que les écrans n'existent pas ; les tests injectent les liens synthétiques ci-dessus. Pas de
   lien vers une route inexistante.
2. **Navigation sans session et pendant le chargement de la session.** Recommandation : sans
   session, seuls les liens publics ; pendant `chargement`, seuls les liens publics également
   (aucun lien réservé affiché puis retiré).
3. **Rôle `admin` et liens des autres rôles.** BIL-F27 (réponse 7) : aucune hiérarchie de rôles.
   Recommandation : la navigation applique la même règle que `GardeRoles` (un lien n'est affiché
   que si l'un des rôles de l'utilisateur figure dans `roles` du lien), donc `admin` ne voit pas
   les liens `customer` seuls.
4. **Thème clair et sombre.** Bascule manuelle ou seulement `prefers-color-scheme` ? Persistance
   du choix ? Recommandation : thème initial = `prefers-color-scheme`, bascule manuelle dans
   l'en-tête (bouton « Thème sombre » avec `aria-pressed`), choix retenu dans `localStorage`
   (clé `billetterie.theme` ; la rule interdit les jetons dans `localStorage`, pas une
   préférence d'affichage), appliqué par un attribut `data-theme` sur `<html>` ; tant qu'aucun
   choix manuel n'est fait, un changement de préférence système est suivi. Pas de script inline
   dans `index.html` pour éviter le flash initial (à voir avec la CSP de Nginx) : à confirmer.
5. **Bibliothèque de styles.** CSS natif, CSS Modules, Tailwind, bibliothèque de composants
   (Radix, React Aria…) ? Recommandation : CSS natif avec propriétés personnalisées (`--couleur-
   fond`, …) par thème et CSS Modules par composant, aucune dépendance ajoutée ; les composants
   sont écrits à la main selon les APG. Vérification du contraste (WCAG AA) : manuelle, hors
   tests automatisés, sauf si Q17 ajoute axe.
6. **Dialogue : `<dialog>` natif ou non.** Recommandation : `<dialog>` natif ouvert par
   `showModal()` (modalité, `inert` du reste de la page, Échap, retour au premier plan fournis
   par le navigateur). jsdom n'implémente pas fidèlement `showModal()` ni le piège du focus : un
   bouchon minimal dans `setupTests.ts` est nécessaire et le cas « la tabulation reste dans le
   dialogue » ne prouve alors que le comportement simulé. Alternative : `div role="dialog"
   aria-modal="true"` avec piège du focus écrit à la main (entièrement testable en jsdom, mais
   plus de code). À trancher.
7. **Dialogue de confirmation : comportement.** Recommandation (APG, action souvent
   destructive) : focus initial sur « Annuler » ; Échap = annuler ; clic hors du dialogue sans
   effet ; à la fermeture, focus rendu à l'élément déclencheur ; libellés par défaut
   « Confirmer » / « Annuler », remplaçables par l'écran ; nom accessible = titre
   (`aria-labelledby`), description = message (`aria-describedby`) ; le dialogue est contrôlé
   (`ouvert`, `surConfirmer`, `surAnnuler`), sans état métier.
8. **Notifications : durée, fermeture, annonce, empilement.** Recommandation : types `succes`,
   `info`, `erreur` ; `succes` / `info` annoncés par une région `role="status"` (polie),
   `erreur` par `role="alert"` ; bouton « Fermer la notification » sur chacune ; fermeture
   automatique après 5 s pour `succes` / `info`, jamais pour `erreur` ; minuterie suspendue au
   survol et au focus (WCAG 2.2.1) ; plusieurs notifications empilées, la plus récente en bas ;
   la notification ne prend jamais le focus. Fournie par un fournisseur et un hook
   (`useNotifications().notifier(...)`) ou par un composant seul : à trancher (recommandation :
   fournisseur + hook, sans logique métier).
9. **Tableau paginé : pagination contrôlée ou côté client.** Recommandation : contrôlée, le
   tableau reçoit une page `{elements, page, size, total}` (forme `commun.pagination.Page` des
   conventions) et appelle `surChangerPage(numero)` ; l'écran fait la requête. Commandes
   « Page précédente » / « Page suivante » dans un `nav aria-label="Pagination"`, texte
   « Page <page> sur <nombre de pages> », boutons désactivés aux bornes ; pas de tri ni de
   choix de `size` dans ce ticket ; colonnes déclarées par `{entete, rendu}` ; `<caption>` ou
   `aria-label` obligatoire pour nommer le tableau. Tableau sans élément : état vide (Q14)
   rendu à la place du tableau.
10. **Tableau : état chargement pendant le changement de page.** Recommandation : hors du
    tableau (l'écran affiche `Chargement` ou garde la page précédente avec `aria-busy="true"`
    sur le tableau) ; le tableau accepte seulement une prop `occupe` qui pose `aria-busy` et
    désactive la pagination.
11. **Champ de formulaire : types, erreurs, obligatoire.** Recommandation : un composant
    `ChampFormulaire` (libellé visible obligatoire, `id` par `useId`) pour `text`, `email`,
    `number`, `password`, plus `select` et `textarea` si besoin d'un écran (à confirmer) ;
    erreur = une chaîne (`erreur?: string`), affichée sous le champ, liée par
    `aria-describedby`, avec `aria-invalid="true"` ; aide facultative aussi liée par
    `aria-describedby` ; obligatoire = attribut `required` et mention « (obligatoire) » dans le
    libellé. Le passage des `erreurs` d'un Problem Details (`champ` = `body.email`) vers le bon
    champ reste à l'écran (logique hors composant), à confirmer.
12. **Bouton : variantes, type, état occupé.** Recommandation : variantes `principal`,
    `secondaire`, `danger` (style seulement) ; `type="button"` par défaut (évite une soumission
    involontaire, `type="submit"` explicite) ; prop `occupe` → `disabled` et `aria-busy="true"`,
    libellé conservé ; `disabled` natif plutôt que `aria-disabled`.
13. **Carte : structure.** Recommandation : `<article>` nommé par son titre
    (`aria-labelledby`), titre `h2` par défaut, niveau réglable (`niveauTitre`), zones contenu
    et actions facultatives ; jamais la carte entière cliquable.
14. **États communs chargement et vide.** Recommandation : `Chargement` = `role="status"`,
    texte par défaut « Chargement… » (remplaçable), comme « Chargement de la session… » de
    `GardeRoles` (qui pourrait l'utiliser) ; `Vide` = message fourni par l'écran (pas de texte
    par défaut métier), action facultative ; état erreur = le `<Erreur>` existant, sans nouveau
    composant.
15. **Mise en page : pied de page, lien d'évitement, `<main>`, focus après navigation.** Le
    ticket ne fixe ni le contenu du pied de page ni l'ordre de tabulation. Recommandation :
    pied de page minimal (« Billetterie », sans lien tant qu'aucune page légale n'existe) ;
    lien d'évitement « Aller au contenu » en premier élément focalisable (WCAG 2.4.1) ;
    la mise en page porte `<main id="contenu" tabIndex={-1}>` et les pages ne rendent plus leur
    propre `<main>` (`PageAccueil`, `PageIntrouvable`, `PageAccesRefuse` à adapter, sinon deux
    `main`) ; à chaque changement de route, focus déplacé sur `<main>` (ou son `h1`). Pas de
    menu repliable (mobile) dans ce ticket.
16. **Lien actif.** Recommandation : `aria-current="page"` sur le lien de la route courante
    (`NavLink` de React Router le pose).
17. **Définition de « navigation complète au clavier » (CA2) et outillage a11y.**
    Recommandation : tout élément interactif de la mise en page (lien d'évitement, liens de
    navigation, bascule de thème, « Se connecter » / « Se déconnecter », liens du pied de page)
    est atteint par Tab dans l'ordre visuel, puis Maj+Tab en sens inverse, sans piège ; liens
    activés par Entrée, boutons par Entrée et Espace ; focus visible (contour non nul,
    vérifiable seulement dans un vrai navigateur, d'où le parcours). Ajouter un contrôle
    automatique (`vitest-axe` en composant, `@axe-core/playwright` en parcours) : utile mais
    ajoute deux dépendances ; recommandation : non dans ce ticket.
18. **Contrainte « aucun appel d'API » et `<Erreur>`.** `Erreur.tsx` importe `convertirErreur`
    de `src/api/problemes.ts` (conversion pure, sans requête). Recommandation : autorisé ; la
    vérification par commande interdit dans `src/composants/` les imports de `src/api/client`,
    `src/api/echos`, `src/api/genere`, de `@tanstack/react-query` et tout `fetch(`.
19. **Galerie de composants.** Recommandation : aucune page ni route de démonstration
    (cohérent avec BIL-F27, réponse 9) ; pas de Storybook.

## CA1 : chaque composant a au moins un test

### Mise en page (en-tête avec connexion, navigation selon le rôle, pied de page)

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_la_mise_en_page_porte_l_en_tete_la_navigation_le_contenu_et_le_pied_de_page` (dépend de Q15) | composant | `MiseEnPage` sous `MemoryRouter`, session non connectée, enfant `<h1>Contenu de test</h1>` | un seul `banner`, un `navigation` nommé « Navigation principale », un seul `main` contenant « Contenu de test », un seul `contentinfo` ; le bouton « Se connecter » de l'en-tête existant est dans `banner` |
| `test_les_pages_existantes_s_affichent_dans_un_seul_contenu_principal` (paramétré `/`, `/route-inconnue`) (dépend de Q15) | composant | `RoutesApplication` sous `MemoryRouter` | h1 « Billetterie » puis « Page introuvable » ; exactement un `main` dans le document ; les cas BIL-F27 de `RoutesApplication.test.tsx` restent verts |
| `test_sans_session_la_navigation_ne_montre_que_les_liens_publics` (dépend de Q1, Q2) | composant | session `non-connecte`, configuration de liens synthétiques (un public « Accueil », un par rôle) | lien « Accueil » présent ; aucun des trois liens réservés (état vide) |
| `test_pendant_le_chargement_de_la_session_la_navigation_n_affiche_aucun_lien_reserve` (dépend de Q2) | composant | session `chargement` | seuls les liens publics ; aucun lien réservé dans le DOM (état chargement) |
| `test_la_navigation_montre_les_liens_du_role_de_l_utilisateur` (paramétré `customer`, `partner`, `admin`) (dépend de Q1, Q3) | composant | session `connecte`, `roles` = `[<rôle>]`, mêmes liens | lien public et lien du rôle présents ; liens des deux autres rôles absents, y compris pour `admin` (aucune hiérarchie) (état succès) |
| `test_un_lien_reserve_a_plusieurs_roles_apparait_pour_chacun` (dépend de Q1, Q3) | composant | lien synthétique `roles` = `["partner", "admin"]` ; sessions `partner`, `admin`, `customer` | visible pour `partner` et `admin`, absent pour `customer` |
| `test_le_lien_de_la_page_courante_porte_aria_current_page` (dépend de Q16) | composant | `MemoryRouter` sur `/espace-client-test`, session `customer` | ce lien a `aria-current="page"` ; « Accueil » ne l'a pas |
| `test_le_pied_de_page_affiche_son_contenu` (dépend de Q15) | composant | `MiseEnPage`, session quelconque | `contentinfo` contient « Billetterie » |

### Bouton

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_le_bouton_est_nomme_par_son_libelle_et_declenche_son_action_au_clic_a_entree_et_a_espace` | composant | `<Bouton surClic={espion}>Valider le test</Bouton>` ; clic, focus + `{Enter}`, focus + `{ }` | `getByRole("button", { name: "Valider le test" })` ; espion appelé 3 fois |
| `test_le_bouton_ne_soumet_pas_de_formulaire_par_defaut` (dépend de Q12) | composant | bouton sans `type` dans un `<form onSubmit={espion}>` | `type="button"` ; clic sans soumission ; avec `type="submit"`, une soumission |
| `test_un_bouton_desactive_ne_declenche_pas_son_action` | composant | `desactive` ; clic et `{Enter}` | `toBeDisabled()` ; espion jamais appelé |
| `test_un_bouton_occupe_est_annonce_occupe_et_ne_declenche_pas_son_action` (dépend de Q12) | composant | `occupe` | `aria-busy="true"`, `toBeDisabled()`, nom accessible inchangé ; deux clics sans appel |
| `test_chaque_variante_rend_un_bouton_natif` (paramétré `principal`, `secondaire`, `danger`) (dépend de Q12) | composant | une variante par rendu | élément `button` natif, même nom accessible ; seule la présentation change (attribut ou classe, non vérifié) |

### Champ de formulaire avec erreurs

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_le_champ_est_associe_a_son_libelle_visible` | composant | `ChampFormulaire` libellé « Adresse e-mail », `type="email"` | `getByLabelText("Adresse e-mail")` trouve un `textbox` ; le libellé est visible (élément `label`) |
| `test_la_saisie_remonte_la_valeur_au_parent` | composant | champ contrôlé, `surChanger` espion ; `user.type(..., "client.test@exemple.test")` | espion appelé avec la valeur saisie ; valeur affichée celle de la prop |
| `test_un_champ_sans_erreur_n_est_pas_marque_invalide` | composant | aucune erreur | pas d'`aria-invalid="true"` ; aucune description d'erreur |
| `test_un_champ_en_erreur_est_marque_invalide_et_decrit_par_son_message` (dépend de Q11) | composant | `erreur` = « Adresse e-mail de test invalide » | `aria-invalid="true"` ; `toHaveAccessibleDescription` contient le message ; le message est visible sous le champ (état erreur) |
| `test_l_aide_et_l_erreur_font_toutes_deux_partie_de_la_description` (dépend de Q11) | composant | `aide` = « Format nom@domaine », `erreur` comme ci-dessus | la description accessible contient les deux textes |
| `test_un_champ_obligatoire_est_annonce_obligatoire` (dépend de Q11) | composant | `obligatoire` | `toBeRequired()` ; « (obligatoire) » dans le nom accessible |
| `test_deux_champs_du_meme_libelle_ont_des_identifiants_distincts` | composant | deux `ChampFormulaire` « Adresse e-mail » rendus ensemble | deux `id` différents ; chaque libellé pointe sur son champ ; chaque erreur décrit son seul champ |
| `test_chaque_type_de_champ_est_associe_a_son_libelle` (paramétré `text`, `email`, `number`, `password`, `select`, `textarea`) (dépend de Q11) | composant | un champ par type, erreur synthétique | élément du rôle attendu (`textbox`, `spinbutton`, `combobox`…, `password` par libellé) ; libellé et description d'erreur associés |

### Tableau paginé

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_le_tableau_rend_un_tableau_nomme_avec_en_tetes_de_colonnes_et_lignes` (dépend de Q9) | composant | page `{elements: 3 lignes synthétiques, page: 1, size: 20, total: 3}`, colonnes « Libellé », « Montant (centimes) », nom « Éléments de test » | `getByRole("table", { name: "Éléments de test" })` ; 2 `columnheader` ; 3 lignes de données (`row` hors en-tête) avec les valeurs fournies (état succès) |
| `test_la_pagination_affiche_la_page_courante_sur_le_nombre_de_pages` (dépend de Q9) | composant | `page: 2, size: 20, total: 45` | dans `navigation` « Pagination » : « Page 2 sur 3 » |
| `test_page_suivante_et_page_precedente_demandent_la_page_voisine_sans_requete` (dépend de Q9) | composant | `page: 2, size: 20, total: 45`, `surChangerPage` espion | « Page suivante » → espion(3) ; « Page précédente » → espion(1) ; affichage inchangé tant que la prop `page` ne change pas (contrôlé) ; aucune requête (MSW) |
| `test_les_commandes_de_pagination_sont_desactivees_aux_bornes` (paramétré : `page: 1` ; `page: 3` ; `total` ≤ `size`) (dépend de Q9) | composant | `size: 20`, `total: 45` ou `5` | première page : « Page précédente » désactivée ; dernière : « Page suivante » désactivée ; une seule page : les deux désactivées (ou pagination masquée, selon Q9) |
| `test_un_tableau_sans_element_affiche_l_etat_vide` (dépend de Q9, Q14) | composant | `{elements: [], page: 1, size: 20, total: 0}`, message vide « Aucun élément de test » | message affiché ; aucun `table` ni pagination (état vide) |
| `test_un_tableau_occupe_est_annonce_occupe_et_bloque_la_pagination` (dépend de Q10) | composant | `occupe`, `page: 2, total: 45` | `aria-busy="true"` sur le tableau ; « Page précédente » et « Page suivante » désactivées (état chargement) |
| `test_la_pagination_se_manipule_au_clavier` (dépend de Q9) | composant | `page: 2, total: 45` ; `user.tab()` jusqu'à « Page suivante », `{Enter}` | focus atteint les deux commandes dans l'ordre ; Entrée appelle `surChangerPage(3)` |

### Carte

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_la_carte_est_un_article_nomme_par_son_titre_avec_son_contenu` (dépend de Q13) | composant | titre « Carte de test », contenu « Contenu de test » | `getByRole("article", { name: "Carte de test" })` ; `heading` niveau 2 « Carte de test » ; contenu présent |
| `test_le_niveau_du_titre_de_la_carte_est_reglable` (dépend de Q13) | composant | `niveauTitre={3}` | `heading` niveau 3 |
| `test_la_carte_rend_ses_actions` (dépend de Q13) | composant | actions : `<Bouton>Action de test</Bouton>` | bouton présent dans l'article ; l'article lui-même n'est ni `button` ni `link` |

### Dialogue de confirmation

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_un_dialogue_ferme_n_est_pas_expose` | composant | `ouvert={false}` | `queryByRole("dialog")` nul |
| `test_le_dialogue_ouvert_est_modal_nomme_par_son_titre_et_decrit_par_son_message` (dépend de Q6, Q7) | composant | `ouvert`, titre « Confirmer l'action de test », message « Cette action de test est définitive. » | `getByRole("dialog")` avec nom accessible = titre et description = message ; modal (`aria-modal="true"` ou `<dialog>` ouvert par `showModal`) ; boutons « Confirmer » et « Annuler » |
| `test_a_l_ouverture_le_focus_va_sur_annuler` (dépend de Q7) | composant | passage de `ouvert` de `false` à `true` | « Annuler » `toHaveFocus()` |
| `test_confirmer_appelle_la_confirmation_une_seule_fois` | composant | `surConfirmer`, `surAnnuler` espions ; clic sur « Confirmer » | `surConfirmer` appelé 1 fois ; `surAnnuler` jamais |
| `test_annuler_et_echap_annulent_sans_confirmer` (paramétré : clic « Annuler » ; `{Escape}`) (dépend de Q7) | composant | mêmes espions | `surAnnuler` appelé 1 fois ; `surConfirmer` jamais |
| `test_un_clic_hors_du_dialogue_ne_le_ferme_pas` (dépend de Q7) | composant | clic sur l'arrière-plan | aucun espion appelé ; dialogue toujours ouvert |
| `test_la_tabulation_reste_dans_le_dialogue` (dépend de Q6) | composant | bouton déclencheur hors du dialogue ; Tab et Maj+Tab répétés 4 fois | le focus alterne entre « Annuler » et « Confirmer », jamais sur le déclencheur (avec `<dialog>` natif : bouchon jsdom, voir Q6) |
| `test_a_la_fermeture_le_focus_revient_au_declencheur` (dépend de Q7) | composant | bouton « Ouvrir le dialogue de test » dans un parent de test qui ouvre puis ferme (Échap) | après fermeture, le déclencheur `toHaveFocus()` |
| `test_les_libelles_des_boutons_sont_remplacables` (dépend de Q7) | composant | `libelleConfirmer` = « Supprimer l'élément de test », `libelleAnnuler` = « Garder » | boutons trouvés par ces noms |

### Notification

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_une_notification_de_succes_est_annoncee_dans_une_region_de_statut` (dépend de Q8) | composant | `notifier({type: "succes", message: "Opération de test réussie"})` | message dans un élément `role="status"` (état succès) |
| `test_une_notification_d_erreur_est_annoncee_en_alerte` (dépend de Q8) | composant | `type: "erreur"`, message « Échec de test » | message dans un élément `role="alert"` (état erreur) |
| `test_fermer_la_notification_la_retire` (dépend de Q8) | composant | une notification ; clic, puis au clavier `{Enter}` sur « Fermer la notification » | message retiré du DOM |
| `test_une_notification_de_succes_disparait_apres_sa_duree` (dépend de Q8) | composant | minuteries simulées ; `succes` | présente à 4 999 ms ; absente après 5 000 ms |
| `test_une_notification_d_erreur_ne_disparait_pas_seule` (dépend de Q8) | composant | minuteries simulées ; `erreur` ; avance de 60 s | toujours présente |
| `test_le_survol_ou_le_focus_suspend_la_fermeture_automatique` (paramétré : survol ; focus sur « Fermer la notification ») (dépend de Q8) | composant | minuteries simulées ; `succes` ; survol ou focus à 3 s, avance jusqu'à 10 s | toujours présente ; à la sortie, disparaît après le temps restant |
| `test_une_notification_ne_prend_pas_le_focus` (dépend de Q8) | composant | un bouton de test focalisé, puis `notifier(...)` | le bouton de test garde le focus |
| `test_plusieurs_notifications_s_empilent_dans_l_ordre` (dépend de Q8) | composant | trois `notifier` successifs (« Notification de test 1 » à « 3 ») | trois messages présents, dans l'ordre d'émission ; fermer la 2e laisse la 1re et la 3e |

### États communs : chargement, vide, erreur

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_l_etat_chargement_est_annonce_en_statut` (dépend de Q14) | composant | `<Chargement />` puis `<Chargement libelle="Chargement des éléments de test…" />` | `role="status"` contenant « Chargement… » puis le libellé fourni (état chargement) |
| `test_l_etat_vide_affiche_le_message_et_l_action_fournis_par_l_ecran` (dépend de Q14) | composant | `<Vide message="Aucun élément de test" action={<Bouton>Créer un élément de test</Bouton>} />` | message visible ; bouton présent ; sans `action`, aucun bouton (état vide) |
| `test_l_etat_erreur_sans_identifiant_de_correlation_n_affiche_pas_de_reference` | composant | `<Erreur probleme>` avec un problème converti synthétique, `correlationId` = `null` | `role="alert"` avec titre et détail ; aucun texte « Référence » |
| Cas existants BIL-F27 (`Erreur.test.tsx`) : `test_le_composant_d_erreur_annonce_le_titre_le_detail_et_la_reference_en_alerte`, `test_le_composant_d_erreur_liste_les_erreurs_d_une_requete_invalide`, `test_le_message_affiche_est_celui_du_serveur_quel_que_soit_le_code`, `test_une_erreur_qui_n_est_pas_un_probleme_donne_le_message_generique`, `test_une_panne_reseau_donne_le_message_generique` | composant | inchangées | inchangé : « Référence : <correlationId> » affiché (état erreur avec identifiant de corrélation) |

### Thème clair et sombre

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_sans_choix_enregistre_le_theme_suit_la_preference_du_systeme` (paramétré : `prefers-color-scheme: dark` vrai ; faux) (dépend de Q4) | composant | `window.matchMedia` simulé, `localStorage` vide | `document.documentElement` porte `data-theme="sombre"` puis `"clair"` |
| `test_la_bascule_de_theme_change_le_theme_et_annonce_son_etat` (dépend de Q4) | composant | préférence claire ; clic puis `{Enter}` sur le bouton « Thème sombre » | après le 1er : `data-theme="sombre"`, `aria-pressed="true"` ; après le 2e : `"clair"`, `aria-pressed="false"` |
| `test_le_choix_de_theme_est_retenu_au_rechargement` (dépend de Q4) | composant | choix sombre, démontage, nouveau rendu avec préférence système claire | `data-theme="sombre"` ; `localStorage` ne contient que la clé de thème (aucune autre donnée) |
| `test_un_changement_de_preference_du_systeme_est_suivi_sans_choix_manuel` (dépend de Q4) | composant | aucun choix ; événement `change` du `matchMedia` simulé vers sombre ; puis, après un choix manuel clair, nouvel événement vers sombre | 1er : `"sombre"` ; 2e : reste `"clair"` |

## CA2 : navigation complète au clavier sur la mise en page

Sens retenu pour « complète » : voir Q17.

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_la_tabulation_parcourt_toute_la_mise_en_page_dans_l_ordre_visuel` (paramétré : non connecté ; connecté `customer`) (dépend de Q1, Q4, Q15, Q17) | composant | `MiseEnPage` sous `MemoryRouter`, liens synthétiques, enfant contenant un bouton « Action du contenu de test » ; `user.tab()` répété depuis `document.body` | ordre de focus : « Aller au contenu », liens de navigation visibles, bascule de thème, « Se connecter » (ou « Se déconnecter »), « Action du contenu de test », éléments focalisables du pied de page ; aucun élément interactif sauté ; aucun élément masqué focalisé |
| `test_maj_tab_parcourt_la_mise_en_page_en_sens_inverse_sans_piege` (dépend de Q17) | composant | même rendu ; focus sur le dernier élément, `{Shift>}{Tab}{/Shift}` répété | ordre exactement inverse ; le focus atteint « Aller au contenu » puis quitte le document (aucun piège) |
| `test_le_lien_d_evitement_amene_le_focus_au_contenu_principal` (dépend de Q15) | composant | focus sur « Aller au contenu », `{Enter}` | `main` `toHaveFocus()` ; Tab suivant : « Action du contenu de test » |
| `test_un_lien_de_navigation_s_active_a_entree_et_deplace_le_focus_sur_le_contenu` (dépend de Q1, Q15) | composant | session `customer`, route de test `/espace-client-test` déclarée par le test ; focus sur « Lien client de test », `{Enter}` | page de test affichée ; `aria-current="page"` sur le lien ; focus sur `main` (ou son `h1`) |
| `test_les_boutons_de_l_en_tete_s_activent_a_entree_et_a_espace` (paramétré : « Se connecter » ; « Se déconnecter » ; bascule de thème) (dépend de Q4) | composant | session imposée avec `seConnecter` / `seDeconnecter` espions | Entrée puis Espace appellent chacun l'action une fois (bascule : le thème change à chaque touche) |
| `test_la_mise_en_page_se_parcourt_entierement_au_clavier` (dépend de Q1, Q4, Q15, Q17) | parcours | `make up` ; `client.test` connecté par l'aide existante ; retour sur `http://localhost/` ; uniquement `page.keyboard` (Tab, Maj+Tab, Entrée, Espace) | chaque élément focalisé de la mise en page a un contour de focus visible (`getComputedStyle(...).outlineStyle` ≠ `none` ou `box-shadow` non nul) ; ordre identique au cas composant ; Entrée sur « Aller au contenu » met le focus dans `main` ; Espace sur la bascule change `data-theme` ; Entrée sur « Se déconnecter » ramène à l'accueil avec « Se connecter » focalisable |

## Contrainte : composants sans logique métier, aucun appel d'API

| Cas | Niveau | Données | Attendu |
|---|---|---|---|
| `test_aucun_composant_de_base_n_emet_de_requete` | composant | rendu successif de chaque composant (mise en page, bouton, champ, tableau avec pagination manipulée, carte, dialogue ouvert puis confirmé, notification, chargement, vide, erreur, bascule de thème) ; écoute `serveurMsw.events.on("request:start")` | aucune requête émise (en plus de `onUnhandledFrame: "error"`) |

Vérification par commandes (PowerShell, depuis `frontend/`) :

| Commande | Attendu |
|---|---|
| `Select-String -Path src\composants\*.tsx -Exclude *.test.tsx -Pattern "api/client","api/echos","api/genere","@tanstack/react-query","fetch\("` (dépend de Q18) | aucune occurrence ; `api/problemes` (conversion pure) toléré |
| `Select-String -Path src\composants\*.tsx -Exclude *.test.tsx -Pattern "useSession"` | seulement dans `EnTete.tsx` et le composant de navigation (lecture de session, pas de règle métier) |
| `npm run typecheck`, `npm run lint`, `npm run build`, `npm run test -- --run` | code de sortie 0 (ESLint `jsx-a11y` sans erreur) |

## Couverture

| Critère | Cas |
|---|---|
| CA1 (mise en page) | `test_la_mise_en_page_porte_l_en_tete_la_navigation_le_contenu_et_le_pied_de_page`, `test_les_pages_existantes_s_affichent_dans_un_seul_contenu_principal`, `test_sans_session_la_navigation_ne_montre_que_les_liens_publics`, `test_pendant_le_chargement_de_la_session_la_navigation_n_affiche_aucun_lien_reserve`, `test_la_navigation_montre_les_liens_du_role_de_l_utilisateur`, `test_un_lien_reserve_a_plusieurs_roles_apparait_pour_chacun`, `test_le_lien_de_la_page_courante_porte_aria_current_page`, `test_le_pied_de_page_affiche_son_contenu` ; en-tête : cas BIL-F27 existants |
| CA1 (bouton) | `test_le_bouton_est_nomme_par_son_libelle_et_declenche_son_action_au_clic_a_entree_et_a_espace`, `test_le_bouton_ne_soumet_pas_de_formulaire_par_defaut`, `test_un_bouton_desactive_ne_declenche_pas_son_action`, `test_un_bouton_occupe_est_annonce_occupe_et_ne_declenche_pas_son_action`, `test_chaque_variante_rend_un_bouton_natif` |
| CA1 (champ) | `test_le_champ_est_associe_a_son_libelle_visible`, `test_la_saisie_remonte_la_valeur_au_parent`, `test_un_champ_sans_erreur_n_est_pas_marque_invalide`, `test_un_champ_en_erreur_est_marque_invalide_et_decrit_par_son_message`, `test_l_aide_et_l_erreur_font_toutes_deux_partie_de_la_description`, `test_un_champ_obligatoire_est_annonce_obligatoire`, `test_deux_champs_du_meme_libelle_ont_des_identifiants_distincts`, `test_chaque_type_de_champ_est_associe_a_son_libelle` |
| CA1 (tableau paginé) | `test_le_tableau_rend_un_tableau_nomme_avec_en_tetes_de_colonnes_et_lignes`, `test_la_pagination_affiche_la_page_courante_sur_le_nombre_de_pages`, `test_page_suivante_et_page_precedente_demandent_la_page_voisine_sans_requete`, `test_les_commandes_de_pagination_sont_desactivees_aux_bornes`, `test_un_tableau_sans_element_affiche_l_etat_vide`, `test_un_tableau_occupe_est_annonce_occupe_et_bloque_la_pagination`, `test_la_pagination_se_manipule_au_clavier` |
| CA1 (carte) | `test_la_carte_est_un_article_nomme_par_son_titre_avec_son_contenu`, `test_le_niveau_du_titre_de_la_carte_est_reglable`, `test_la_carte_rend_ses_actions` |
| CA1 (dialogue) | `test_un_dialogue_ferme_n_est_pas_expose`, `test_le_dialogue_ouvert_est_modal_nomme_par_son_titre_et_decrit_par_son_message`, `test_a_l_ouverture_le_focus_va_sur_annuler`, `test_confirmer_appelle_la_confirmation_une_seule_fois`, `test_annuler_et_echap_annulent_sans_confirmer`, `test_un_clic_hors_du_dialogue_ne_le_ferme_pas`, `test_la_tabulation_reste_dans_le_dialogue`, `test_a_la_fermeture_le_focus_revient_au_declencheur`, `test_les_libelles_des_boutons_sont_remplacables` |
| CA1 (notification) | `test_une_notification_de_succes_est_annoncee_dans_une_region_de_statut`, `test_une_notification_d_erreur_est_annoncee_en_alerte`, `test_fermer_la_notification_la_retire`, `test_une_notification_de_succes_disparait_apres_sa_duree`, `test_une_notification_d_erreur_ne_disparait_pas_seule`, `test_le_survol_ou_le_focus_suspend_la_fermeture_automatique`, `test_une_notification_ne_prend_pas_le_focus`, `test_plusieurs_notifications_s_empilent_dans_l_ordre` |
| CA1 (états communs) | `test_l_etat_chargement_est_annonce_en_statut`, `test_l_etat_vide_affiche_le_message_et_l_action_fournis_par_l_ecran`, `test_l_etat_erreur_sans_identifiant_de_correlation_n_affiche_pas_de_reference` ; cinq cas existants de `Erreur.test.tsx` |
| CA1 (thème) | `test_sans_choix_enregistre_le_theme_suit_la_preference_du_systeme`, `test_la_bascule_de_theme_change_le_theme_et_annonce_son_etat`, `test_le_choix_de_theme_est_retenu_au_rechargement`, `test_un_changement_de_preference_du_systeme_est_suivi_sans_choix_manuel` |
| CA2 | `test_la_tabulation_parcourt_toute_la_mise_en_page_dans_l_ordre_visuel`, `test_maj_tab_parcourt_la_mise_en_page_en_sens_inverse_sans_piege`, `test_le_lien_d_evitement_amene_le_focus_au_contenu_principal`, `test_un_lien_de_navigation_s_active_a_entree_et_deplace_le_focus_sur_le_contenu`, `test_les_boutons_de_l_en_tete_s_activent_a_entree_et_a_espace`, `test_la_mise_en_page_se_parcourt_entierement_au_clavier` ; voir aussi `test_la_pagination_se_manipule_au_clavier`, `test_annuler_et_echap_annulent_sans_confirmer`, `test_la_tabulation_reste_dans_le_dialogue` |
| Contrainte | `test_aucun_composant_de_base_n_emet_de_requete` ; commandes `Select-String`, `typecheck`, `lint`, `build`, `test` |

États d'écran (composant) : chargement
(`test_l_etat_chargement_est_annonce_en_statut`,
`test_pendant_le_chargement_de_la_session_la_navigation_n_affiche_aucun_lien_reserve`,
`test_un_tableau_occupe_est_annonce_occupe_et_bloque_la_pagination`), vide
(`test_l_etat_vide_affiche_le_message_et_l_action_fournis_par_l_ecran`,
`test_un_tableau_sans_element_affiche_l_etat_vide`,
`test_sans_session_la_navigation_ne_montre_que_les_liens_publics`), erreur
(`test_l_etat_erreur_sans_identifiant_de_correlation_n_affiche_pas_de_reference`, cas existants
de `Erreur.test.tsx`, `test_un_champ_en_erreur_est_marque_invalide_et_decrit_par_son_message`,
`test_une_notification_d_erreur_est_annoncee_en_alerte`), succès
(`test_le_tableau_rend_un_tableau_nomme_avec_en_tetes_de_colonnes_et_lignes`,
`test_la_navigation_montre_les_liens_du_role_de_l_utilisateur`,
`test_une_notification_de_succes_est_annoncee_dans_une_region_de_statut`).

Parcours : un seul, pour CA2 (le focus visible ne se vérifie que dans un vrai navigateur) ; CA1
n'a pas de parcours (composants isolés, couverts en composant).
