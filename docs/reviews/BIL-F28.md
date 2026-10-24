# Review : BIL-F28, Front : composants de base et mise en page

- Diff relu : `git diff main` (travail non commité : 10 fichiers modifiés, 44 fichiers non suivis
  hors `test-results/`, soit 54 fichiers)
- Verdict : 0 bloquant, 4 à corriger, 9 suggestions

## Points

| # | Classement | Fichier:ligne | Constat | Attendu |
|---|---|---|---|---|
| 1 | à corriger | `frontend/src/notifications/FournisseurNotifications.tsx:103` | La pile n'est rendue que lorsqu'il y a au moins une notification (`notifications.length > 0`), et chaque notification crée sa propre région `role="status"` / `role="alert"` (l. 63-64) déjà remplie au moment où elle est insérée. Les lecteurs d'écran annoncent mal, voire pas du tout, une région live qui arrive dans le DOM avec son contenu, surtout pour `status` (NVDA, VoiceOver). Le plan (Q8) demande que les notifications soient « annoncées ». | Deux régions permanentes, rendues dès le montage du fournisseur et vides au départ (`role="status"` et `role="alert"`), dans lesquelles on insère les notifications de leur type. Les tests actuels (message contenu dans un élément `status` / `alert`) restent valables. |
| 2 | à corriger | `frontend/src/composants/TableauPagine.tsx:83` | `desactive={occupe \|\| page.page <= 1}` (et l. 91) : le bouton que l'utilisateur vient d'activer au clavier passe en `disabled` dès que `occupe` devient vrai, ou quand il atteint une borne (« Page suivante » sur l'avant-dernière page). Le navigateur retire alors le focus, qui retombe sur `body`, et l'utilisateur du clavier perd sa position. Même effet pour `Bouton` avec `occupe` (`frontend/src/composants/Bouton.tsx:32`) sur un bouton de soumission. C'est une conséquence de Q10/Q12 (`disabled` natif), que le plan n'a pas tranchée. | Faire remonter la question au développeur (pas de décision en silence) : `aria-disabled="true"` avec le clic neutralisé pour l'état occupé, ou focus déplacé sur le bouton voisin ou la position une fois la borne atteinte. |
| 3 | à corriger | `frontend/src/theme/FournisseurTheme.tsx:61` | `data-theme` est posé dans un `useEffect`, donc après le premier affichage. Si l'utilisateur a enregistré un choix contraire à la préférence du système (sombre sur un système clair, ou l'inverse), chaque chargement affiche d'abord le thème du système (`:root:not([data-theme])`, `theme.css:39`) puis bascule : le flash initial n'est évité que lorsqu'il n'y a aucun choix enregistré. | Lire `billetterie.theme` et poser `data-theme` avant le premier rendu, sans script inline (donc compatible avec la CSP de Q4) : par exemple dans `main.tsx` avant `createRoot`, ou dans l'initialiseur d'état avec `useLayoutEffect`. Sinon, consigner ce flash comme résiduel accepté dans les décisions du ticket. |
| 4 | à corriger | `.gitignore:388` | Un dossier `test-results/` non suivi existe à la racine du dépôt. Seul `frontend/test-results/` est ignoré. Son `.last-run.json` indique `"status": "failed"`, un reste du rouge mesuré ou d'un lancement depuis la racine, alors que les 8 tests Playwright passent. Un `git add .` le committerait. | Supprimer `test-results/` à la racine avant le commit et, si ce mode de lancement est prévu, ignorer `/test-results/` dans `.gitignore` (décision à faire valider par le développeur). |
| 5 | suggestion | `frontend/src/composants/DialogueConfirmation.tsx:59` | `onCancel` appelle `preventDefault()` et aucun `onClose` n'est géré. Dans Chromium, au deuxième Échap sans activation de l'utilisateur entre les deux, `cancel` n'est plus annulable et le `<dialog>` se ferme de lui-même. Si l'écran garde alors `ouvert={true}` (action en cours, par exemple), l'état React et l'état du DOM divergent, et l'effet ne rouvre plus le dialogue. | Écouter `close` pour réaligner l'état (appeler `surAnnuler` si le dialogue a été fermé hors de la prop), ou documenter que `surAnnuler` doit toujours passer `ouvert` à `false`. |
| 6 | suggestion | `frontend/src/composants/Navigation.tsx:33` | `end` est posé sur tous les liens, alors que le commentaire ne le justifie que pour « / ». Un futur lien `/commandes` ne portera donc pas `aria-current="page"` sur `/commandes/123`. | `end` réservé à `chemin === "/"`, ou rendu configurable dans `LienNavigation`. |
| 7 | suggestion | `frontend/src/composants/TableauPagine.tsx:63` | Les clés React des colonnes sont `colonne.entete` (aussi l. 73) : deux colonnes au même en-tête, ou dont l'en-tête est vide (colonne d'actions), donnent des clés en double. | Clé par l'index ou par un identifiant de colonne facultatif. |
| 8 | suggestion | `frontend/src/composants/TableauPagine.tsx:50` | Une page vide alors que `total > 0` (page au-delà de la dernière, après une suppression par exemple) affiche l'état vide sans pagination : l'utilisateur ne peut plus revenir en arrière. Ce cas n'est pas prévu par le plan. | Le soumettre en question : garder la pagination lorsque `total > 0`, ou laisser l'écran ramener la page. |
| 9 | suggestion | `frontend/src/composants/TableauPagine.tsx:57` | Le conteneur `overflow-x: auto` n'est pas focalisable. Sur un navigateur qui ne rend pas focalisables les zones défilantes, un tableau large ne peut pas défiler au clavier. | `tabIndex={0}`, plus `role="region"` et un nom accessible, sur le conteneur défilant (ou laisser tel quel, en connaissance de cause). |
| 10 | suggestion | `frontend/src/composants/TableauPagine.tsx:88` | « Page X sur Y » est un simple `<p>` : après un changement de page, rien n'est annoncé aux lecteurs d'écran. | `aria-live="polite"` sur la position, ou annonce par l'écran. |
| 11 | suggestion | `frontend/src/composants/EnTete.module.css:29` | `EnTete` redéfinit son propre style de bouton (`.action`) au lieu de réutiliser `Bouton`, d'où deux styles de bouton principal à maintenir. | Utiliser `<Bouton>` dans `EnTete` (sans changer les noms accessibles des tests BIL-F27). |
| 12 | suggestion | `frontend/src/theme/theme.css:38` | Les valeurs du thème sombre sont écrites deux fois (l. 38-59 et 61-80) et peuvent diverger. | Commentaire « à garder identique » au minimum, ou factorisation avec `light-dark()` et `color-scheme`. |
| 13 | suggestion | `frontend/src/main.tsx:2` | La ligne de commentaire dépasse largement les 100 colonnes du reste du code (Prettier ne replie pas les commentaires). | Replier le commentaire. |

## Grille

| Axe | Résultat |
|---|---|
| Ticket et contrat | Conforme. Étapes 1 à 4 traitées : mise en page avec en-tête, navigation par rôle et pied de page ; bouton, champ, tableau paginé, carte, dialogue, notification ; états chargement, vide et erreur ; thème. CA1 : chaque composant a au moins un test. CA2 : cas composant et parcours Playwright. Aucun contrat d'API concerné. Les décisions du ticket sont toutes appliquées : configuration `{libelle, chemin, roles}` sans hiérarchie (`roles: []` visible par personne), `<dialog>` natif, fournisseurs dans `main.tsx`, un seul `main`, lien d'évitement par JavaScript avec `href="#contenu"` conservé, pagination affichée et désactivée sur une page unique, `children` de l'en-tête avant la connexion. Points 2 et 8 : décisions à faire remonter. |
| Contrainte « aucun appel d'API ni logique métier » | Conforme. Aucun import de `api/client`, `api/echos`, `api/genere` ni de `@tanstack/react-query`, et aucun `fetch(` dans `src/composants`, `src/theme` ni `src/notifications`. `useSession` n'apparaît que dans `EnTete` et `Navigation`. Le tableau est contrôlé, et le passage des `erreurs` d'un Problem Details vers les champs est laissé à l'écran. |
| Accessibilité | Le dialogue est conforme à l'APG : nommé et décrit, focus initial sur « Annuler », Échap annule, clic hors du dialogue sans effet, focus rendu par `showModal`/`close`, refermé au démontage. Champ conforme : `aria-invalid`, `aria-describedby` pour l'aide et l'erreur, `useId`, « (obligatoire) » et `required`. Tableau nommé par `<caption>`, `th scope="col"`, `nav aria-label="Pagination"`. Mise en page conforme : un seul `main`, focus déplacé au changement de route mais pas au premier chargement, ordre de tabulation égal à l'ordre visuel (aucun `order` CSS), focus visible par `:focus-visible` (vérifié par le parcours). Restent les points 1, 2, 9 et 10. |
| Thème | Conforme pour la persistance : seule la clé `billetterie.theme` est écrite, avec des valeurs validées (`clair` / `sombre`) et un stockage indisponible toléré. Aucun jeton dans `localStorage`. `prefers-color-scheme` est suivi tant qu'aucun choix manuel n'est fait, et l'écouteur est retiré au démontage. Reste le flash quand le choix enregistré diffère de la préférence du système : point 3. |
| Minuteries des notifications | Conforme. `clearTimeout` est appelé au nettoyage de l'effet, donc au démontage et à la fermeture. Survol et focus suspendent la minuterie en conservant le temps restant, et la sortie du focus vers un descendant ne la relance pas. Une `erreur` n'a pas de minuterie, et la notification ne prend jamais le focus. |
| Rules | Conforme (`frontend.md`, `securite.md`, `tests.md`) : TypeScript strict, données synthétiques, aucun secret, CSS Modules et propriétés personnalisées. Aucune couleur codée en dur dans les modules, sauf l'ombre `rgb(0 0 0 / 15%)` des notifications, qui est acceptable. Point 4 (hygiène du dépôt). |
| Sécurité | Conforme. Aucune route protégée ajoutée, aucun jeton manipulé, et le filtrage de la navigation repose sur la session de l'appelant (affichage seulement : `GardeRoles` reste la garde). |
| Résilience | Sans objet (front, aucun appel entre services). |
| Tests | Conformes au plan : tous les cas du plan sont présents et nommés comme lui. `setupTests.ts`, `vite.config.ts` (bloc `test`), `playwright.config.ts`, `EnTete.test.tsx` et `e2e/connexion.spec.ts` sont inchangés. Le bouchon de `<dialog>` est dupliqué (complet dans `DialogueConfirmation.test.tsx`, minimal dans `AucuneRequete.test.tsx`, gardé par `typeof showModal`), conformément à la décision du développeur. Il reste limité au fichier, puisque Vitest isole chaque fichier. Tests BIL-F26/F27 modifiés dans les limites prévues : `PageAccueil.test.tsx` rendu sous `MiseEnPage` avec un `main` unique (même intention), lien de `RoutesApplication.test.tsx` ciblé par son nom avec la même attente (`href="/"`), un cas ajouté à `Erreur.test.tsx` sans toucher les cinq cas existants. Aucune assertion retirée. Limite connue, déjà consignée en Q6 : le piège du focus du dialogue n'est prouvé que par le bouchon jsdom. |
| Non-régression BIL-F26/F27 | Conforme. Le comportement d'`EnTete` est inchangé : mêmes libellés et conditions, la navigation et la bascule s'ajoutent en `children`. `Erreur` n'a pas changé. Les gardes n'ont pas changé. Les pages n'ont plus de `<main>`, `PageRappelConnexion` compris. |
| Lisibilité | Bonne : nommage français cohérent, commentaires d'en-tête utiles, aucun code mort. Points 6, 7, 11, 12 et 13. |

## Seconde review

- Diff relu : `git diff main` et fichiers non suivis (10 fichiers modifiés, 46 fichiers non
  suivis hors ce rapport, dont les nouveaux `frontend/src/theme/preference.ts` et
  `frontend/src/main.test.tsx`, soit 56 fichiers)
- Référence : `docs/tickets/BIL-F28.md`, section « Décisions (validation 2) »
- Verdict : 0 bloquant, 2 à corriger, 3 suggestions

### Suivi des points de la première review

| # | Décision (validation 2) | Résultat |
|---|---|---|
| 1 | Retenu : deux zones permanentes | Traité. `FournisseurNotifications.tsx:112-119` : `role="status"` et `role="alert"` rendus dès le montage, vides au départ, jamais masqués (`.region` en `display: flex`, jamais `display: none`, `FournisseurNotifications.module.css:10-15`). Une pile vide n'a aucune hauteur et ne gêne pas les clics. Ordre chronologique par type : accepté par le développeur. Nouveau défaut : point S1. |
| 2 | Retenu : `aria-disabled` et clic ignoré | Traité. `Bouton.tsx:34-52` : `inactif` et `occupe` posent `aria-disabled="true"` sans `disabled`, et le gestionnaire `click` appelle `preventDefault()` puis sort. Entrée et Espace sur un `<button>` passent par `click`, et la soumission implicite (Entrée dans un champ) passe par un `click` synthétique sur le bouton par défaut : son annulation bloque aussi la soumission. `desactive` reste un `disabled` natif. `TableauPagine.tsx:92` et `:102` utilisent `inactif`, et le focus est conservé à la borne (test dédié). Le CSS couvre les deux états (`Bouton.module.css:15-16`, survol exclu). Manque de test sur la soumission : point S2. |
| 3 | Retenu : thème avant `createRoot` | Traité. `main.tsx:26` appelle `appliquerThemeInitial()` avant `createRoot`, uniquement dans `demarrerApplication` : l'iframe de reconnexion silencieuse (`main.tsx:45-49`) n'est pas touchée, elle n'importe que la feuille `theme.css`, sans effet. `FournisseurTheme` part des mêmes lectures (`useState(lireChoix)`, `useState(themeDuSysteme)`, `preference.ts:21-28` et `:12-14`), donc la même valeur, et l'effet de montage réécrit la même valeur sans bascule. Limite résiduelle : point S3. |
| 4 | Retenu ; `.gitignore` à la main | Traité pour le dossier : `test-results/` n'existe plus à la racine. Rappel : `/test-results/` reste à ajouter à la main par le développeur dans `.gitignore` (ligne 388 : seul `frontend/test-results/` y figure). |
| 5 | Retenu : gestionnaire `close` ; contrat documenté | Traité, sans double appel. Échap annulable : `surAnnuler` une fois, puis la fermeture par la prop pose `fermetureDemandee` (l. 54), et `surFermeture` le remet à faux sans rappeler (l. 82-85). Échap non annulable (Chromium) : `surEchap` sort sans appel (l. 71-75), le navigateur ferme, `surFermeture` appelle `surAnnuler` une seule fois, et l'effet ne refait rien puisque `element.open` est faux. Démontage et double effet de `StrictMode` : `fermetureDemandee` est posé avant `close()` (l. 64), donc l'événement `close` asynchrone n'appelle pas `surAnnuler`. Le contrat « `surAnnuler` doit passer `ouvert` à false » est documenté (l. 15-19), accepté par le développeur. |
| 6 | Retenu : `end` seulement sur « / » | Traité (`Navigation.tsx:34`), avec un test sur un sous-chemin. |
| 7 | Retenu : clés uniques | Traité (`TableauPagine.tsx:70-82`, clé par index, justifiée pour des colonnes fixes), avec un test sans avertissement de clé. |
| 8 | Non retenu | Sans objet. |
| 9 | Retenu : zone focalisable | Traité (`TableauPagine.tsx:63`, `role="region"`, nommée par la légende, `tabIndex={0}`). `eslint-disable-next-line` local et justifié : accepté par le développeur. |
| 10 | Retenu : annonce de la position | Traité (`TableauPagine.tsx:97`, `aria-live="polite"`). |
| 11 | Non retenu | Sans objet. |
| 12 | Retenu : `light-dark()` | Traité. Chaque couleur est écrite une seule fois (`theme.css:9-25`), et `color-scheme` suit `data-theme` (l. 39-47). Support : `light-dark()` natif à partir de Chrome 123, Firefox 120 et Safari 17.5, mais la cible CSS par défaut de Vite 8 est plus ancienne et Lightning CSS le compile. La sortie du build (`frontend/dist/assets/index-pFzCKTjl.css`) le confirme : `--couleur-fond:var(--lightningcss-light,#fff)var(--lightningcss-dark,#14161b)`, avec `--lightningcss-light` et `--lightningcss-dark` basculés sur `:root`, dans la media query et dans `:root[data-theme=sombre]`. Plus aucun `light-dark(` brut dans le bundle, et le `rgb(... / 55%)` du voile est converti. Le repli ne demande que les propriétés personnalisées. |
| 13 | Retenu | Traité (`main.tsx:1-5`). |

### Points

| # | Classement | Fichier:ligne | Constat | Attendu |
|---|---|---|---|---|
| S1 | à corriger | `frontend/src/notifications/FournisseurNotifications.tsx:113` | Nouveau défaut introduit par la correction du point 1. `role="status"` et `role="alert"` portent implicitement `aria-atomic="true"` (WAI-ARIA). Tant que chaque notification avait sa région, cela restait sans effet. Maintenant que toutes les notifications d'un type partagent la même région (l. 113 et 116), chaque ajout fait relire toute la région : toutes les notifications encore affichées, avec chacune leur « Fermer la notification ». Avec trois succès empilés, le troisième relit les trois. | `aria-atomic="false"` explicite sur les deux régions, pour que seule la notification ajoutée soit annoncée, et une assertion sur cet attribut dans `FournisseurNotifications.test.tsx`. |
| S2 | à corriger | `frontend/src/composants/Bouton.test.tsx:76` | Le code bloque bien la soumission (`preventDefault()` sur `click`, `Bouton.tsx:39`), mais aucun test ne le prouve pour `type="submit"`. Les cas « occupé » (l. 76 et 100) n'utilisent que `type="button"` avec `surClic`. C'est pourtant l'usage principal d'`occupe` (formulaire de commande en cours d'envoi) et la protection contre une double soumission. La prop `inactif` n'a pas non plus de cas dans `Bouton.test.tsx` : elle n'est couverte que par `TableauPagine.test.tsx`. | Un cas qui rend `<Bouton type="submit" occupe>` (et `inactif`) dans un `<form>` avec un champ texte, puis vérifie que ni le clic, ni Entrée sur le bouton, ni Entrée dans le champ (soumission implicite) n'appellent `onSubmit`. Étape `tests`, par `unit-test-writer`. |
| S3 | suggestion | `frontend/src/main.tsx:26` | Le flash est supprimé pour le contenu React, mais `main.tsx` est un script `type="module"`, donc différé (`frontend/index.html:10`). Une fois la feuille CSS chargée, si le bundle JS arrive plus tard, le navigateur peut peindre la page avant l'exécution : le `#root` est vide, mais le fond de `body` suit `:root:not([data-theme])`, donc la préférence du système. Le flash qui reste est limité à la couleur de fond, quand le choix enregistré contredit le système. C'est la limite connue de l'option « pas de script inline ». | Consigner ce résiduel dans les décisions du ticket, ou l'accepter tel quel. |
| S4 | suggestion | `frontend/src/notifications/FournisseurNotifications.tsx:112` | Limite antérieure, pas une régression. Les régions sont hors du `<dialog>`. Pendant qu'un `DialogueConfirmation` modal est ouvert, `showModal` rend le reste de la page inerte : une notification émise à ce moment n'est ni annoncée ni joignable (« Fermer la notification »). | Documenter, dans le commentaire d'en-tête ou dans `notifications.ts`, que l'écran ferme le dialogue avant de notifier. |
| S5 | suggestion | `frontend/src/composants/TableauPagine.tsx:63` | La zone de défilement et le tableau portent le même nom (la légende). Un lecteur d'écran annonce « Éléments de test, région » puis « tableau Éléments de test ». C'est redondant mais sans gêne réelle. | Laisser tel quel, ou donner à la région un nom distinct (« Défilement du tableau … »). |

### Tests ajustés

- `Bouton.test.tsx` : `toBeDisabled` est devenu `aria-disabled="true"` pour l'état occupé, et
  l'action est toujours vérifiée non déclenchée au clic, à Entrée et à Espace. Le nouveau cas
  « devient occupé » prouve que le focus est conservé. `desactive` reste testé avec
  `toBeDisabled`. Aucune assertion affaiblie.
- `TableauPagine.test.tsx` : aux bornes, `aria-disabled` plus un clic qui ne déclenche rien ;
  hors bornes, `toBeEnabled` et l'absence d'`aria-disabled`. Nouveaux cas : focus conservé à la
  borne (avec un second Entrée sans effet), clés en double sans avertissement, position annoncée,
  zone focalisable et nommée. Le parcours au clavier ajoute un arrêt sur la zone de défilement.
  Aucune assertion affaiblie.
- `FournisseurNotifications.test.tsx` : les régions sont présentes et vides au montage, puis
  chaque type va dans sa région. Le survol vise le texte du message au lieu de la région, ce qui
  revient au même puisque l'événement `mouseenter` de React remonte jusqu'à la notification.
  Aucune assertion affaiblie.
- `DialogueConfirmation.test.tsx` : deux cas ajoutés (fermeture par le navigateur : une seule
  annulation ; fermeture par la prop : aucune annulation). Le bouchon émet `close` de façon
  synchrone, alors que le navigateur l'émet plus tard. Ce n'est pas gênant, puisque le drapeau
  `fermetureDemandee` couvre les deux ordres.
- `Navigation.test.tsx` : un cas ajouté pour un sous-chemin. `main.test.tsx` (nouveau) relève
  `data-theme` au moment de `createRoot` pour les deux choix contraires au système. Il ne couvre
  pas le chemin de l'iframe silencieuse, mais le code montre que ce chemin n'appelle ni
  `appliquerThemeInitial` ni `createRoot`.
- Le bloc `test` de `frontend/vite.config.ts` est inchangé (identique à `main`).

### Grille

| Axe | Résultat |
|---|---|
| Ticket et contrat | Conforme. Tous les points retenus en validation 2 sont traités, et les points non retenus (8, 11) ne sont pas touchés. La prop `inactif`, l'ordre par type, l'`eslint-disable` local et le contrat du dialogue sont conformes aux décisions acceptées. |
| Rules | Conforme (`frontend.md`, `securite.md`, `tests.md`). Rappel : `/test-results/` est à ajouter à la main dans `.gitignore`. |
| Sécurité | Conforme. `preference.ts` ne lit et n'écrit que `billetterie.theme`, et aucune valeur n'est validée hors de `clair` / `sombre`. |
| Résilience | Sans objet. |
| Accessibilité | Points S1, S4, S5. |
| Tests | Aucune assertion affaiblie. Bloc `test` de `vite.config.ts` inchangé. Point S2. |
| Lisibilité | Bonne : `preference.ts` factorise proprement les lectures partagées, et les commentaires expliquent les choix (drapeau `fermetureDemandee`, clés par index, exception ESLint). Point S3. |
