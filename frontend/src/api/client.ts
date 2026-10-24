// Client d'API unique (openapi-fetch, types générés de src/api/genere/). Son intercepteur
// ajoute le jeton d'accès en Bearer et un X-Correlation-Id UUID v4 par requête ; sur 401,
// un renouvellement silencieux puis un seul rejeu.
import createClient, { type Client, type Middleware } from "openapi-fetch";

import { urlApi } from "../config";
import type { CheminsApi } from "./genere";

/** Chemins de tous les contrats, réunis par l'index généré (`npm run api:gen`). */
export type { CheminsApi };

export type ClientApi = Client<CheminsApi>;

/** Accès du client au jeton gardé en mémoire par le fournisseur d'authentification. */
export interface SourceJeton {
  /** Jeton d'accès courant, `null` sans session. */
  jetonAcces(): string | null;
  /** Renouvellement silencieux : nouveau jeton d'accès, `null` en cas d'échec. */
  renouveler(): Promise<string | null>;
}

let sourceCourante: SourceJeton | null = null;

/** Branche (ou débranche avec `null`) la source de jeton utilisée par le client. */
export function brancherSourceJeton(source: SourceJeton | null): void {
  sourceCourante = source;
}

function poserEnTetes(requete: Request, jeton: string | null): void {
  requete.headers.set("X-Correlation-Id", crypto.randomUUID());
  if (jeton === null || jeton === "") {
    requete.headers.delete("Authorization");
  } else {
    requete.headers.set("Authorization", `Bearer ${jeton}`);
  }
}

/** Intercepteur openapi-fetch : Authorization, X-Correlation-Id, renouvellement sur 401. */
export function intercepteurApi(source: () => SourceJeton | null): Middleware {
  // Copie intacte de chaque requête (corps compris), gardée pour un éventuel rejeu.
  const copies = new Map<string, Request>();
  return {
    onRequest({ request, id }) {
      poserEnTetes(request, source()?.jetonAcces() ?? null);
      copies.set(id, request.clone());
      return request;
    },
    async onResponse({ request, response, options, id }) {
      const copie = copies.get(id);
      copies.delete(id);
      const sourceActive = source();
      // Sans jeton envoyé, renouveler ne changerait rien : l'erreur est rendue telle quelle.
      if (
        response.status !== 401 ||
        copie === undefined ||
        sourceActive === null ||
        !request.headers.has("Authorization")
      ) {
        return undefined;
      }
      const nouveauJeton = await sourceActive.renouveler();
      if (nouveauJeton === null) {
        return undefined;
      }
      // Un seul rejeu : sa réponse, même 401, est rendue au code appelant.
      poserEnTetes(copie, nouveauJeton);
      return options.fetch(copie);
    },
    onError({ id }) {
      copies.delete(id);
      return undefined;
    },
  };
}

/** Origine de `urlApi()` : les chemins du contrat commencent déjà par /api/v1. */
function origineApi(): string {
  return new URL(urlApi(), window.location.origin).origin;
}

/** Client d'API ; `baseUrl` = origine de `urlApi()` (les chemins commencent par /api/v1). */
export function clientApi(): ClientApi {
  const client = createClient<CheminsApi>({ baseUrl: origineApi() });
  client.use(intercepteurApi(() => sourceCourante));
  return client;
}
