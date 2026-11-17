// Exécution d'un appel du client généré : données et indicateur de mode dégradé, ou `ErreurApi`
// (Problem Details converti, message générique pour une panne réseau ou un corps illisible).
import { convertirCorps, convertirErreur, ErreurApi } from "./problemes";

/** Données d'une lecture et indicateur de mode dégradé. */
export interface Lecture<T> {
  donnees: T;
  /** Vrai quand la réponse vient du cache de secours (`X-Cache-Stale: true`). */
  perimee: boolean;
}

const EN_TETE_PERIME = "X-Cache-Stale";

export interface ResultatBrut<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Exécute un appel du client généré ; lève `ErreurApi` (Problem Details ou message générique). */
export async function lire<T>(appel: () => Promise<ResultatBrut<T>>): Promise<Lecture<T>> {
  let resultat: ResultatBrut<T>;
  try {
    resultat = await appel();
  } catch (erreur) {
    // Panne réseau : message générique.
    throw new ErreurApi(convertirErreur(erreur));
  }
  const { data, error, response } = resultat;
  if (!response.ok || data === undefined) {
    throw new ErreurApi(convertirCorps(error, response));
  }
  return { donnees: data, perimee: response.headers.get(EN_TETE_PERIME) === "true" };
}
