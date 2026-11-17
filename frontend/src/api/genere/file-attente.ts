// Fichier généré par `npm run api:gen` depuis services/file-attente/openapi.yaml.
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
  "/api/v1/queues/{seance_id}/position": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Lire ma position dans la file d'attente d'une séance (rôle customer)
     * @description Position de l'appelant du jeton, relue par la salle d'attente toutes les quelques secondes. EN_ATTENTE : position et attente estimée. ADMIS : jeton d'admission signé, à transmettre à creerCommande dans l'en-tête X-Admission-Token jusqu'à admission_expire_le ; le même jeton est rendu à chaque lecture.
     */
    get: operations["lirePositionFile"];
    put?: never;
    /**
     * Entrer dans la file d'attente d'une séance (rôle customer)
     * @description Place l'appelant du jeton en fin de file de la séance, si elle est sous file. Un appelant déjà présent garde sa place : la requête répond 200 avec sa position actuelle (EN_ATTENTE), ou son jeton d'admission s'il est déjà admis et que l'admission n'a pas expiré ; rafraîchir la page ne fait donc pas perdre sa place. Après expiration de l'admission, l'appelant n'est plus dans la file et rentre en fin de file.
     */
    post: operations["entrerFile"];
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
    /**
     * StatutFile
     * @description EN_ATTENTE : l'appelant attend son tour. ADMIS : admis par une vague, il peut commander avec son jeton d'admission jusqu'à admission_expire_le.
     * @enum {string}
     */
    StatutFile: "EN_ATTENTE" | "ADMIS";
    /** PositionFile */
    PositionFile: {
      /**
       * Seance Id
       * Format: uuid
       */
      seance_id: string;
      statut: components["schemas"]["StatutFile"];
      /**
       * Position
       * @description Rang dans la file, 1 pour le prochain admis ; null si ADMIS.
       */
      position: number | null;
      /**
       * Attente Estimee Secondes
       * @description Attente estimée en secondes, d'après la position, la taille et le rythme des vagues d'admission ; null si ADMIS.
       */
      attente_estimee_secondes: number | null;
      /**
       * Jeton Admission
       * @description Jeton d'admission signé par file-attente (séance, appelant, expiration), à transmettre à creerCommande dans l'en-tête X-Admission-Token ; null si EN_ATTENTE.
       */
      jeton_admission: string | null;
      /**
       * Admission Expire Le
       * @description Fin de validité du jeton d'admission ; null si EN_ATTENTE.
       */
      admission_expire_le: string | null;
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
export type StatutFile = components["schemas"]["StatutFile"];
export type PositionFile = components["schemas"]["PositionFile"];
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
      /** @description L'instance et Redis répondent. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Sante"];
        };
      };
      /** @description Redis ne répond pas. */
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
  lirePositionFile: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        seance_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Position de l'appelant (EN_ATTENTE) ou son admission (ADMIS). */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["PositionFile"];
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
      /** @description Rôle manquant, la file est réservée aux clients (ROLE_MANQUANT). */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Aucune file pour cette séance (QUEUE_NOT_FOUND), ou l'appelant n'y est pas, jamais entré ou admission expirée (QUEUE_POSITION_NOT_FOUND). */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Identifiant invalide (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Redis injoignable ou trop lent, position ni écrite ni lue (FILE_INDISPONIBLE). */
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
  entrerFile: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        seance_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description L'appelant était déjà dans la file ; position ou admission inchangée. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["PositionFile"];
        };
      };
      /** @description L'appelant entre en fin de file (statut EN_ATTENTE). */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["PositionFile"];
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
      /** @description Rôle manquant, la file est réservée aux clients (ROLE_MANQUANT). */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Aucune file pour cette séance, séance inconnue ou non sous file (QUEUE_NOT_FOUND). */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Identifiant invalide (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Redis injoignable ou trop lent, position ni écrite ni lue (FILE_INDISPONIBLE). */
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
}
