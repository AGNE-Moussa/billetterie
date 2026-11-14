// Fonctions d'API du service commandes (client connecté, rôle customer), typées par
// src/api/genere/commandes.ts.
import { clientApi } from "./client";
import type { Commande } from "./genere/commandes";
import { lire } from "./lecture";

/**
 * `POST /api/v1/orders` sans `carte_test` (`creerCommande`) : réserve les places, la commande
 * reste `EN_ATTENTE` jusqu'à `expire_le`. `cleIdempotence` : une par tentative de réservation ;
 * rejouée, la requête rend la même commande au lieu d'en créer une seconde.
 */
export async function reserverPlaces(
  seanceId: string,
  placeIds: readonly string[],
  cleIdempotence: string,
): Promise<Commande> {
  const { donnees } = await lire(() =>
    clientApi().POST("/api/v1/orders", {
      params: { header: { "Idempotency-Key": cleIdempotence } },
      // `carte_test: null` explicite : sans carte (le type généré le rend obligatoire).
      body: { seance_id: seanceId, place_ids: [...placeIds], carte_test: null },
    }),
  );
  return donnees;
}

/** `GET /api/v1/orders/{commande_id}` (`lireCommande`). */
export async function lireCommande(commandeId: string): Promise<Commande> {
  const { donnees } = await lire(() =>
    clientApi().GET("/api/v1/orders/{commande_id}", {
      params: { path: { commande_id: commandeId } },
    }),
  );
  return donnees;
}

/** `POST /api/v1/orders/{commande_id}/payment` (`payerCommande`) avec la carte de test. */
export async function payerCommande(commandeId: string, carteTest: string): Promise<Commande> {
  const { donnees } = await lire(() =>
    clientApi().POST("/api/v1/orders/{commande_id}/payment", {
      params: { path: { commande_id: commandeId } },
      body: { carte_test: carteTest },
    }),
  );
  return donnees;
}
