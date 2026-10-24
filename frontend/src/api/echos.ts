// Fonctions d'API du service echo, typées par src/api/genere/echo.ts (CA3 : un contrat modifié
// casse leur compilation).
import { clientApi } from "./client";
import type { EchoPage, operations } from "./genere/echo";
import { convertirCorps, convertirErreur, ErreurApi } from "./problemes";

export type ParametresListeEchos = NonNullable<operations["listerEchos"]["parameters"]["query"]>;

/** `GET /api/v1/echos` : une page de messages ; lève `ErreurApi` en cas d'erreur. */
export async function listerEchos(parametres: ParametresListeEchos = {}): Promise<EchoPage> {
  let resultat;
  try {
    resultat = await clientApi().GET("/api/v1/echos", { params: { query: parametres } });
  } catch (erreur) {
    // Panne réseau : message générique.
    throw new ErreurApi(convertirErreur(erreur));
  }
  const { data, error, response } = resultat;
  if (!response.ok || data === undefined) {
    throw new ErreurApi(convertirCorps(error, response));
  }
  const { elements, page, size, total } = data;
  return { elements, page, size, total };
}
