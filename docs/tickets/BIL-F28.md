# BIL-F28 : Front : composants de base et mise en page

- **Branche** : `feat/bil-f28-front-composants`
- **Dépend de** : BIL-F27
- **Service** : frontend

## Objectif

Fournir les composants réutilisables du projet pour que chaque écran métier ne s'occupe que du
métier.

## Étapes

- [x] 1. Mise en page : en-tête avec connexion, navigation selon le rôle, pied de page.
- [x] 2. Composants : bouton, champ de formulaire avec erreurs, tableau paginé, carte, dialogue
  de confirmation, notification.
- [x] 3. États communs : chargement, vide, erreur (avec l'identifiant de corrélation affiché).
- [x] 4. Thème clair et sombre ; tests Testing Library de chaque composant.

## Critères d'acceptance

- [x] CA1 : chaque composant a au moins un test
- [x] CA2 : navigation complète au clavier sur la mise en page

## Contraintes

- Composants sans logique métier ; aucun appel d'API dedans.

## Décisions (validation 1)

- Toutes les recommandations du plan retenues (`docs/test-plans/BIL-F28.md`, questions 1 à 19) :
  navigation par configuration `{libelle, chemin, roles}` sans hiérarchie de rôles ; thème
  `prefers-color-scheme` puis bascule manuelle retenue dans `localStorage` (`data-theme` sur
  `<html>`) ; CSS natif et CSS Modules ; `<dialog>` natif ; notifications par fournisseur et hook ;
  tableau à pagination contrôlée ; un seul `<main>` dans la mise en page, lien d'évitement ; pas
  d'axe ni de galerie de composants.

## Décisions (squelette)

- Test d'accueil BIL-F26 adapté (rendu sous `MiseEnPage`, un seul `main`).
- Fournisseurs de thème et de notifications dans `main.tsx`, hors de `MiseEnPage`.
- `roles` absent = lien public ; `roles: []` = visible par personne.
- Bouchon `showModal` / `close` dans `setupTests.ts`, écrit à l'étape tests.

## Décisions (tests)

- Le hook interdit `setupTests.ts` à `unit-test-writer` : le bouchon de `<dialog>` reste local
  (complet dans `DialogueConfirmation.test.tsx`, minimal dans `AucuneRequete.test.tsx`, gardé
  par `typeof showModal !== "function"`).
- Au premier chargement, le focus ne va pas sur `main` (seulement au changement de route) : le
  premier Tab atteint « Aller au contenu ».
- Rouge mesuré : Vitest 81 failed, 84 passed (tous sur assertion) ; Playwright 1 failed
  (« Aller au contenu » introuvable).

## Décisions (implémentation)

- Deux défauts de test corrigés par `unit-test-writer`, sans retirer d'assertion : lien de la
  page introuvable ciblé par son nom (la mise en page ajoute deux liens) ; survol des
  notifications par `fireEvent.mouseEnter` / `mouseLeave` sur la région, fausses minuteries
  strictes (`shouldAdvanceTime` écarté : la dérive du temps réel rendait le test instable).
  Marqueur ramené à `tests` le temps de ces corrections.
- `<main>` retiré aussi de `PageRappelConnexion` (un seul `main`).
- Tableau d'une seule page : pagination affichée, boutons désactivés.
- « Aller au contenu » déplace le focus par JavaScript, sans `#contenu` dans l'adresse
  (`href="#contenu"` conservé).
- `EnTete` reçoit navigation et bascule en `children`, avant la connexion dans l'ordre de
  tabulation.

## Décisions (validation 2)

- Review `docs/reviews/BIL-F28.md` : les 4 points à corriger et les suggestions sûres repartent.
- Notifications : deux zones `status` et `alert` permanentes, vides au départ.
- Boutons de pagination et bouton occupé : `aria-disabled="true"` et clic ignoré au lieu de
  `disabled`, pour garder le focus ; `desactive` reste un `disabled` natif.
- Thème posé sur `<html>` avant `createRoot` dans `main.tsx` (pas de flash, pas de script inline).
- `test-results/` de la racine supprimé ; `/test-results/` ajouté au `.gitignore`.
- Suggestions retenues : gestionnaire `close` du dialogue, `end` seulement sur « / », clés de
  colonnes uniques, couleurs sombres sans doublon, ligne longue de `main.tsx`, annonce de
  « Page X sur Y », zone de défilement du tableau focalisable.
- Non retenues : `EnTete` réutilisant `Bouton` ; page vide avec `total > 0`.
- Tests ajustés d'abord (marqueur `tests`) : `toBeDisabled` devient `aria-disabled` pour ces
  boutons, nouveaux cas rouges pour les comportements ajoutés.
- Après correction : prop `inactif` ajoutée à `Bouton` (`aria-disabled` sans `aria-busy`,
  utilisée aux bornes de la pagination) ; thème initial par `theme/preference.ts`
  (`appliquerThemeInitial` avant `createRoot`) ; couleurs en `light-dark()`.
- `eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex` justifié sur la zone de
  défilement du tableau (`role="region"`), plutôt qu'une exception globale.
- Notifications : ordre chronologique conservé par type ; les erreurs s'affichent sous les
  succès et infos.
- Dialogue contrôlé : `surAnnuler` doit passer `ouvert` à false (contrat documenté, pas de
  réouverture).
- `/test-results/` dans `.gitignore` : ajouté à la main par le développeur (fichier interdit
  aux agents).

## Décisions (seconde review)

- S1 : `aria-atomic="false"` explicite sur les deux zones de notification (elles sont partagées).
- S2 : tests ajoutés : un `type="submit"` `occupe` ou `inactif` ne soumet pas le formulaire (clic,
  Entrée sur le bouton, Entrée dans un champ) ; cas propre pour `inactif`.
- Limites acceptées : léger flash possible de la couleur de fond avant l'exécution du module
  (S3) ; une notification émise pendant un dialogue modal est inerte, ni annoncée ni joignable
  (S4).
- S5 (nom redondant de la zone de défilement) non retenu.
