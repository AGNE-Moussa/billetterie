// Politique de nouvel essai des requêtes TanStack Query (client de main.tsx) : une erreur d'API
// au format Problem Details dont le code dit que la requête elle-même est en cause (ressource
// introuvable, paramètres invalides, droits) n'est pas rejouée ; une panne (réseau, 5xx) l'est,
// deux fois au plus.

import { ErreurApi } from "./problemes";

const NOMBRE_MAXIMAL_D_ESSAIS_SUPPLEMENTAIRES = 2;

/** Codes techniques d'erreur passagère : rejouer peut réussir. */
function estPassagere(code: string): boolean {
  return code.endsWith("_INDISPONIBLE");
}

/** Fonction `retry` de TanStack Query. */
export function reessayerRequete(echecs: number, erreur: unknown): boolean {
  if (echecs >= NOMBRE_MAXIMAL_D_ESSAIS_SUPPLEMENTAIRES) {
    return false;
  }
  if (erreur instanceof ErreurApi && erreur.probleme.code !== null) {
    return estPassagere(erreur.probleme.code);
  }
  return true;
}
