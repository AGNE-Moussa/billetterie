// Configuration des liens de la navigation principale : un lien sans `roles` est public ; sinon
// il n'est affiché que si l'utilisateur porte l'un des rôles listés (sans hiérarchie).
import type { Role } from "./auth/roles";

export interface LienNavigation {
  libelle: string;
  chemin: string;
  /** Rôles admis ; absent : lien public. */
  roles?: readonly Role[];
}

/**
 * Liens livrés par l'application (table de docs/front/routes.md) : le catalogue, public ; les
 * commandes et les billets du client (BIL-021).
 */
export const LIENS_NAVIGATION: readonly LienNavigation[] = [
  { libelle: "Événements", chemin: "/" },
  { libelle: "Mes commandes", chemin: "/commandes", roles: ["customer"] },
  { libelle: "Mes billets", chemin: "/billets", roles: ["customer"] },
];
