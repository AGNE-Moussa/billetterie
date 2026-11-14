// Fonctions d'API du service billets (lecture publique des places), typées par
// src/api/genere/billets.ts.
import { clientApi } from "./client";
import type { Place } from "./genere/billets";
import { lire } from "./lecture";

/** Taille de page maximale de `listerPlaces` (`size` ≤ 100, conventions de pagination). */
const TAILLE_PAGE_PLACES = 100;

/**
 * `GET /api/v1/seats?seance_id=` (`listerPlaces`), toutes les pages : les places de la séance,
 * par rang puis numéro, avec leur disponibilité.
 */
export async function listerToutesLesPlaces(seanceId: string): Promise<Place[]> {
  const places: Place[] = [];
  for (let page = 1; ; page += 1) {
    const { donnees } = await lire(() =>
      clientApi().GET("/api/v1/seats", {
        params: { query: { seance_id: seanceId, page, size: TAILLE_PAGE_PLACES } },
      }),
    );
    places.push(...donnees.elements);
    if (donnees.elements.length === 0 || places.length >= donnees.total) {
      return places;
    }
  }
}
