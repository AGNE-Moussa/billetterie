// Fichier généré par `npm run api:gen` depuis services/echo/openapi.yaml.
// Ne pas modifier à la main : modifier le contrat puis relancer la génération.

export interface paths {
  "/health": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** État de l'instance, appelé par Consul toutes les 10 s */
    get: operations["sante"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/echos": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Lister les messages enregistrés, page par page (scope echos:read) */
    get: operations["listerEchos"];
    put?: never;
    /** Enregistrer un message (scope echos:write) */
    post: operations["creerEcho"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/echos/{message}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Relire un message enregistré (appelant authentifié) */
    get: operations["lireEcho"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    /** EchoCreation */
    EchoCreation: {
      /**
       * Message
       * @example bonjour
       */
      message: string;
    };
    /** EchoReponse */
    EchoReponse: {
      /** Message */
      message: string;
      /**
       * Instance
       * @description Instance qui a traité la requête.
       */
      instance: string;
      /**
       * Cree Le
       * Format: date-time
       */
      cree_le: string;
    };
    /** EchoPage */
    EchoPage: {
      /** Elements */
      elements: components["schemas"]["EchoReponse"][];
      /** Page */
      page: number;
      /** Size */
      size: number;
      /**
       * Total
       * @description Nombre total de messages enregistrés.
       */
      total: number;
    };
    /** Probleme */
    Probleme: {
      /**
       * Type
       * @default about:blank
       */
      type: string;
      /** Title */
      title: string;
      /** Status */
      status: number;
      /** Detail */
      detail: string;
      /**
       * Code
       * @description Code métier stable, par exemple ECHO_INTROUVABLE.
       */
      code: string;
      /**
       * Correlation Id
       * @description Identifiant de corrélation de la requête (X-Correlation-Id).
       */
      correlation_id?: string | null;
      /**
       * Erreurs
       * @description Détail des champs invalides (code REQUETE_INVALIDE).
       */
      erreurs?:
        | {
            [key: string]: unknown;
          }[]
        | null;
    };
    /** Sante */
    Sante: {
      /**
       * Statut
       * @example ok
       */
      statut: string;
    };
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}
export type EchoCreation = components["schemas"]["EchoCreation"];
export type EchoReponse = components["schemas"]["EchoReponse"];
export type EchoPage = components["schemas"]["EchoPage"];
export type Probleme = components["schemas"]["Probleme"];
export type Sante = components["schemas"]["Sante"];
export type $defs = Record<string, never>;
export interface operations {
  sante: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description L'instance et sa base répondent. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Sante"];
        };
      };
      /** @description La base de données ne répond pas. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
    };
  };
  listerEchos: {
    parameters: {
      query?: {
        page?: number;
        size?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Page de messages enregistrés. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["EchoPage"];
        };
      };
      /** @description Jeton absent, invalide ou expiré (JETON_*). */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Rôle ou scope manquant (ROLE_MANQUANT, SCOPE_MANQUANT). */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Paramètres de pagination invalides (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
    };
  };
  creerEcho: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["EchoCreation"];
      };
    };
    responses: {
      /** @description Message enregistré. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["EchoReponse"];
        };
      };
      /** @description Jeton absent, invalide ou expiré (JETON_*). */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Rôle ou scope manquant (ROLE_MANQUANT, SCOPE_MANQUANT). */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Le message est déjà enregistré (ECHO_EXISTANT). */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Corps invalide (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
    };
  };
  lireEcho: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        message: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Message enregistré, avec l'instance qui a répondu. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["EchoReponse"];
        };
      };
      /** @description Jeton absent, invalide ou expiré (JETON_*). */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Aucun echo pour ce message (ECHO_INTROUVABLE). */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Message invalide (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
    };
  };
}
