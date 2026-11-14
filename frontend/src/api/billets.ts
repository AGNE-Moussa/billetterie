// Fonctions d'API du service billets (lecture publique des places, billets du client connecté),
// typées par src/api/genere/billets.ts.
import { clientApi } from "./client";
import type { Billet, BilletPage, Place } from "./genere/billets";
import { lire } from "./lecture";

/**
 * `GET /api/v1/tickets` (`listerBillets`) : une page des billets de l'appelant, restreinte à une
 * commande si `commandeId` est fourni. Le filtre par appelant est fait par le back (jeton).
 */
export async function listerBillets(
  page: number,
  options: { commandeId?: string; size?: number } = {},
): Promise<BilletPage> {
  const { donnees } = await lire(() =>
    clientApi().GET("/api/v1/tickets", {
      params: { query: { page, size: options.size, commande_id: options.commandeId } },
    }),
  );
  return donnees;
}

/** `GET /api/v1/tickets/{billet_id}` (`lireBillet`) : un billet de l'appelant et son QR code. */
export async function lireBillet(billetId: string): Promise<Billet> {
  const { donnees } = await lire(() =>
    clientApi().GET("/api/v1/tickets/{billet_id}", {
      params: { path: { billet_id: billetId } },
    }),
  );
  return donnees;
}

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
