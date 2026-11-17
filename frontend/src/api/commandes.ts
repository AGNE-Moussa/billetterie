// Fonctions d'API du service commandes (client connecté, rôle customer), typées par
// src/api/genere/commandes.ts.
import { clientApi } from "./client";
import type { Commande, CommandePage } from "./genere/commandes";
import { lire } from "./lecture";

/** `GET /api/v1/orders` (`listerCommandes`) : une page des commandes de l'appelant (jeton). */
export async function listerCommandes(page: number, size?: number): Promise<CommandePage> {
  const { donnees } = await lire(() =>
    clientApi().GET("/api/v1/orders", { params: { query: { page, size } } }),
  );
  return donnees;
}

/**
 * `POST /api/v1/orders` sans `carte_test` (`creerCommande`) : réserve les places, la commande
 * reste `EN_ATTENTE` jusqu'à `expire_le`. `cleIdempotence` : une par tentative de réservation ;
 * rejouée, la requête rend la même commande au lieu d'en créer une seconde. `jetonAdmission` :
 * jeton remis par file-attente pour une séance sous file, envoyé dans `X-Admission-Token`
 * (BIL-015, BIL-023) ; absent, l'en-tête n'est pas envoyé.
 */
export async function reserverPlaces(
  seanceId: string,
  placeIds: readonly string[],
  cleIdempotence: string,
  jetonAdmission: string | null = null,
): Promise<Commande> {
  const enTetes: { "Idempotency-Key": string; "X-Admission-Token"?: string } = {
    "Idempotency-Key": cleIdempotence,
  };
  if (jetonAdmission !== null) {
    enTetes["X-Admission-Token"] = jetonAdmission;
  }
  const { donnees } = await lire(() =>
    clientApi().POST("/api/v1/orders", {
      params: { header: enTetes },
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
