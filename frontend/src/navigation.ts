// Configuration des liens de la navigation principale : un lien sans `roles` est public ; sinon
// il n'est affiché que si l'utilisateur porte l'un des rôles listés (sans hiérarchie).
import type { Role } from "./auth/roles";

export interface LienNavigation {
  libelle: string;
  chemin: string;
  /** Rôles admis ; absent : lien public. */
  roles?: readonly Role[];
}

/** Liens livrés par l'application : seulement « Accueil » tant qu'aucun écran métier n'existe. */
export const LIENS_NAVIGATION: readonly LienNavigation[] = [{ libelle: "Accueil", chemin: "/" }];
