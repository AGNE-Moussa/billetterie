// Fonctions d'API du service file-attente (client connecté, rôle customer), typées par
// src/api/genere/file-attente.ts (BIL-015, front BIL-023).
import { clientApi } from "./client";
import type { PositionFile } from "./genere/file-attente";
import { lire } from "./lecture";

export type { PositionFile };

/**
 * `POST /api/v1/queues/{seance_id}/position` (`entrerFile`) : entre dans la file de la séance.
 * Idempotent : un appelant déjà présent garde sa place, ou retrouve son jeton d'admission s'il
 * est admis (CA1 de BIL-023). 404 `QUEUE_NOT_FOUND` : la séance n'est pas sous file.
 */
export async function entrerFile(seanceId: string): Promise<PositionFile> {
  const { donnees } = await lire(() =>
    clientApi().POST("/api/v1/queues/{seance_id}/position", {
      params: { path: { seance_id: seanceId } },
    }),
  );
  return donnees;
}

/** `GET /api/v1/queues/{seance_id}/position` (`lirePositionFile`) : position ou admission. */
export async function lirePositionFile(seanceId: string): Promise<PositionFile> {
  const { donnees } = await lire(() =>
    clientApi().GET("/api/v1/queues/{seance_id}/position", {
      params: { path: { seance_id: seanceId } },
    }),
  );
  return donnees;
}
