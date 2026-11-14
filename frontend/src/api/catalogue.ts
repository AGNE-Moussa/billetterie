// Fonctions d'API du service catalogue (lectures publiques), typées par src/api/genere/catalogue.ts.
// Chaque lecture rend ses données et `perimee` : vrai si la réponse porte `X-Cache-Stale: true`
// (copie de secours servie parce que la base ne répond pas, mode dégradé).
import { clientApi } from "./client";
import type {
  Evenement,
  EvenementPage,
  Lieu,
  operations,
  Seance,
  SeancePage,
} from "./genere/catalogue";
import { lire, type Lecture } from "./lecture";

export type { Lecture };

export type FiltresEvenements = NonNullable<operations["listerEvenements"]["parameters"]["query"]>;

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

/** `GET /api/v1/shows/{seance_id}` : une séance et ses catégories (`lireSeanceParId`). */
export function lireSeanceParId(seanceId: string): Promise<Lecture<Seance>> {
  return lire(() =>
    clientApi().GET("/api/v1/shows/{seance_id}", { params: { path: { seance_id: seanceId } } }),
  );
}

/** `GET /api/v1/venues/{lieu_id}` (`lireLieu`). */
export function lireLieu(lieuId: string): Promise<Lecture<Lieu>> {
  return lire(() =>
    clientApi().GET("/api/v1/venues/{lieu_id}", { params: { path: { lieu_id: lieuId } } }),
  );
}
