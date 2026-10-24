// Session exposée par le fournisseur d'authentification, lue par le hook useSession.
import type { User } from "oidc-client-ts";
import { createContext, useContext } from "react";

import type { Role } from "./roles";

export const MESSAGE_SESSION_EXPIREE = "Votre session a expiré";

export type StatutSession = "chargement" | "connecte" | "non-connecte";

export interface Session {
  statut: StatutSession;
  /** Utilisateur oidc-client-ts (jetons en mémoire), `null` sans session. */
  utilisateur: User | null;
  /** `preferred_username` du profil, `null` sans session. */
  nomUtilisateur: string | null;
  /** Rôles lus dans le jeton d'accès. */
  roles: readonly Role[];
  /** Vrai après un échec du renouvellement : afficher MESSAGE_SESSION_EXPIREE. */
  sessionExpiree: boolean;
  /**
   * Redirige vers Keycloak ; `pageDeRetour` : chemin rouvert après le rappel. Rend `false` si
   * la redirection n'a pas pu être lancée (Keycloak injoignable).
   */
  seConnecter(pageDeRetour?: string): Promise<boolean>;
  /** Oublie l'utilisateur et ferme la session Keycloak (`signoutRedirect`). */
  seDeconnecter(): Promise<void>;
  /**
   * Termine la connexion depuis l'adresse de rappel (échange du code) ; rend la page de retour.
   * En cas d'échec, la session passe à non connecté et l'erreur est relancée.
   */
  terminerConnexion(adresseRappel: string): Promise<string>;
}

/** Session hors de tout fournisseur : non connecté, actions sans effet. */
export const SESSION_NON_CONNECTEE: Session = {
  statut: "non-connecte",
  utilisateur: null,
  nomUtilisateur: null,
  roles: [],
  sessionExpiree: false,
  seConnecter: () => Promise.resolve(false),
  seDeconnecter: () => Promise.resolve(),
  terminerConnexion: () => Promise.reject(new Error("Aucun fournisseur d'authentification")),
};

export const ContexteSession = createContext<Session>(SESSION_NON_CONNECTEE);

/** Session courante (fournie par FournisseurAuthentification). */
export function useSession(): Session {
  return useContext(ContexteSession);
}
