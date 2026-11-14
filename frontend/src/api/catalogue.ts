// Fonctions d'API du service catalogue (lectures publiques, écritures de l'organisateur), typées
// par src/api/genere/catalogue.ts.
// Chaque lecture rend ses données et `perimee` : vrai si la réponse porte `X-Cache-Stale: true`
// (copie de secours servie parce que la base ne répond pas, mode dégradé).
import { clientApi } from "./client";
import type {
  Evenement,
  EvenementCreation,
  EvenementPage,
  Lieu,
  LieuCreation,
  LieuPage,
  operations,
  Seance,
  SeanceCreation,
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

/** `GET /api/v1/venues` : une page de lieux (`listerLieux`). */
export function listerLieux(page: number, size?: number): Promise<Lecture<LieuPage>> {
  return lire(() => clientApi().GET("/api/v1/venues", { params: { query: { page, size } } }));
}

/** Taille de page maximale (`size` ≤ 100, conventions de pagination). */
const TAILLE_PAGE_MAX = 100;

/** `GET /api/v1/venues` (`listerLieux`), toutes les pages : la liste complète des lieux. */
export async function listerTousLesLieux(): Promise<Lieu[]> {
  const lieux: Lieu[] = [];
  for (let page = 1; ; page += 1) {
    const { donnees } = await listerLieux(page, TAILLE_PAGE_MAX);
    lieux.push(...donnees.elements);
    if (donnees.elements.length === 0 || lieux.length >= donnees.total) {
      return lieux;
    }
  }
}

// Écritures réservées à l'organisateur (scope events:write, rôle admin) : le jeton est posé par
// l'intercepteur du client ; le service revérifie rôle et scope.

/** `POST /api/v1/events` (`creerEvenement`). */
export async function creerEvenement(corps: EvenementCreation): Promise<Evenement> {
  const { donnees } = await lire(() => clientApi().POST("/api/v1/events", { body: corps }));
  return donnees;
}

/** `POST /api/v1/events/{evenement_id}/shows` (`creerSeance`) : programme une séance. */
export async function creerSeance(evenementId: string, corps: SeanceCreation): Promise<Seance> {
  const { donnees } = await lire(() =>
    clientApi().POST("/api/v1/events/{evenement_id}/shows", {
      params: { path: { evenement_id: evenementId } },
      body: corps,
    }),
  );
  return donnees;
}

/** `POST /api/v1/events/{evenement_id}/shows/{seance_id}/cancellation` (`annulerSeance`). */
export async function annulerSeance(evenementId: string, seanceId: string): Promise<Seance> {
  const { donnees } = await lire(() =>
    clientApi().POST("/api/v1/events/{evenement_id}/shows/{seance_id}/cancellation", {
      params: { path: { evenement_id: evenementId, seance_id: seanceId } },
    }),
  );
  return donnees;
}

/** `POST /api/v1/venues` (`creerLieu`). */
export async function creerLieu(corps: LieuCreation): Promise<Lieu> {
  const { donnees } = await lire(() => clientApi().POST("/api/v1/venues", { body: corps }));
  return donnees;
}
