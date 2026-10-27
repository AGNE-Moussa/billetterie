/// <reference types="node" />
// Utilisateurs de test du realm `billetterie` (infra/keycloak/realm-billetterie.json) et lecture
// de leur mot de passe dans le `.env` racine. Aucun mot de passe n'est écrit ici ni affiché :
// un message d'erreur ne nomme que la variable manquante.
import type { Page } from "@playwright/test";

export interface UtilisateurDeTest {
  /** `preferred_username` du realm. */
  nom: string;
  /** Variable du `.env` qui porte son mot de passe. */
  variable: "KEYCLOAK_MDP_CLIENT" | "KEYCLOAK_MDP_ADMIN";
}

// Le revendeur (rôle partner) est un client Client Credentials `revendeur-test` (BIL-003) :
// il ne se connecte pas par le navigateur, il n'a donc pas sa place ici.
export const CLIENT_TEST: UtilisateurDeTest = {
  nom: "client.test",
  variable: "KEYCLOAK_MDP_CLIENT",
};
export const ADMIN_TEST: UtilisateurDeTest = { nom: "admin.test", variable: "KEYCLOAK_MDP_ADMIN" };

export const UTILISATEURS_DE_TEST = [CLIENT_TEST, ADMIN_TEST] as const;

let envCharge = false;

/** Mot de passe de l'utilisateur, lu dans le `.env` racine (ou l'environnement déjà défini). */
export function motDePasse(utilisateur: UtilisateurDeTest): string {
  if (!envCharge && process.env[utilisateur.variable] === undefined) {
    process.loadEnvFile(new URL("../../.env", import.meta.url));
    envCharge = true;
  }
  const valeur = process.env[utilisateur.variable];
  if (valeur === undefined || valeur === "") {
    throw new Error(`Variable ${utilisateur.variable} absente du .env racine.`);
  }
  return valeur;
}

/** Remplit et envoie le formulaire de connexion Keycloak (champs par libellé, bouton par rôle). */
export async function seConnecterSurKeycloak(
  page: Page,
  utilisateur: UtilisateurDeTest,
): Promise<void> {
  await page.getByLabel("Username or email").fill(utilisateur.nom);
  await page.getByLabel("Password", { exact: true }).fill(motDePasse(utilisateur));
  await page.getByRole("button", { name: "Sign In" }).click();
}
