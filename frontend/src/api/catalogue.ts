// Fonctions d'API du service catalogue (lectures publiques), typées par src/api/genere/catalogue.ts.
// Chaque lecture rend ses données et `perimee` : vrai si la réponse porte `X-Cache-Stale: true`
// (copie de secours servie parce que la base ne répond pas, mode dégradé).
import { clientApi } from "./client";
import type { Evenement, EvenementPage, Lieu, operations, SeancePage } from "./genere/catalogue";
import { convertirCorps, convertirErreur, ErreurApi } from "./problemes";

export type FiltresEvenements = NonNullable<operations["listerEvenements"]["parameters"]["query"]>;

/** Données d'une lecture et indicateur de mode dégradé. */
export interface Lecture<T> {
  donnees: T;
  /** Vrai quand la réponse vient du cache de secours (`X-Cache-Stale: true`). */
  perimee: boolean;
}

const EN_TETE_PERIME = "X-Cache-Stale";

interface ResultatBrut<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Exécute un appel du client généré ; lève `ErreurApi` (Problem Details ou message générique). */
async function lire<T>(appel: () => Promise<ResultatBrut<T>>): Promise<Lecture<T>> {
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

/** `GET /api/v1/events` : une page d'événements filtrée (`listerEvenements`). */
export function listerEvenements(filtres: FiltresEvenements = {}): Promise<Lecture<EvenementPage>> {
  return lire(() => clientApi().GET("/api/v1/events", { params: { query: filtres } }));
}

/** `GET /api/v1/events/{evenement_id}` (`lireEvenement`). */
export function lireEvenement(evenementId: string): Promise<Lecture<Evenement>> {
  return lire(() =>
    clientApi().GET("/api/v1/events/{evenement_id}", {
      params: { path: { evenement_id: evenementId } },
    }),
  );
}

/** `GET /api/v1/events/{evenement_id}/shows` : une page de séances (`listerSeances`). */
export function listerSeances(
  evenementId: string,
  page: number,
  size?: number,
): Promise<Lecture<SeancePage>> {
  return lire(() =>
    clientApi().GET("/api/v1/events/{evenement_id}/shows", {
      params: { path: { evenement_id: evenementId }, query: { page, size } },
    }),
  );
}

/** `GET /api/v1/venues/{lieu_id}` (`lireLieu`). */
export function lireLieu(lieuId: string): Promise<Lecture<Lieu>> {
  return lire(() =>
    clientApi().GET("/api/v1/venues/{lieu_id}", { params: { path: { lieu_id: lieuId } } }),
  );
}
