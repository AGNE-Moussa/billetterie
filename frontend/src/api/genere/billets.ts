// Fichier généré par `npm run api:gen` depuis services/billets/openapi.yaml.
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
  "/api/v1/seats": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Disponibilité des places d'une séance, page par page (route publique)
     * @description Ordre stable par rang, puis numéro. Une séance inconnue ou sans place répond 200 avec elements vide.
     */
    get: operations["listerPlaces"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/seats/{place_id}/lock": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    /**
     * Verrouiller une place pour une commande (scope seats:lock ; client services seulement)
     * @description Verrou Redis SET NX PX dont le propriétaire (valeur de la clé) est la commande (règles métier 1 et 2). confirmation à false : durée de réservation (10 min par défaut, configurable) ; idempotent, un nouvel appel pour la même commande répond 200 et prolonge le verrou. confirmation à true : durée de confirmation (1 h par défaut, configurable), accordée seulement à la commande qui détient déjà le verrou, sinon 409 SEAT_ALREADY_TAKEN ; Commandes l'appelle juste avant Paiements. Billets supprime le verrou une fois le billet émis ; ticketing.order.expired ne libère la place que si la valeur de la clé est cette commande.
     */
    put: operations["verrouillerPlace"];
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
    /** Place */
    Place: {
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /**
       * Seance Id
       * Format: uuid
       */
      seance_id: string;
      /** Rang */
      rang: string;
      /** Numero */
      numero: number;
      /**
       * Categorie Id
       * Format: uuid
       * @description Catégorie de places tarifée de la séance (Catalogue).
       */
      categorie_id: string;
      /**
       * Disponible
       * @description Faux si la place est verrouillée ou vendue.
       */
      disponible: boolean;
    };
    /** PlacePage */
    PlacePage: {
      /** Elements */
      elements: components["schemas"]["Place"][];
      /** Page */
      page: number;
      /** Size */
      size: number;
      /**
       * Total
       * @description Nombre total de places de la séance.
       */
      total: number;
    };
    /** VerrouCreation */
    VerrouCreation: {
      /**
       * Seance Id
       * Format: uuid
       * @description Séance de la commande ; une place d'une autre séance répond SEAT_NOT_FOUND.
       */
      seance_id: string;
      /**
       * Commande Id
       * Format: uuid
       * @description Commande propriétaire du verrou.
       */
      commande_id: string;
      /**
       * Confirmation
       * @description Faux, durée de réservation (10 min par défaut) ; vrai, durée de confirmation (1 h par défaut), seulement pour la commande qui détient le verrou.
       * @default false
       */
      confirmation: boolean;
    };
    /** Verrou */
    Verrou: {
      /**
       * Place Id
       * Format: uuid
       */
      place_id: string;
      /**
       * Seance Id
       * Format: uuid
       */
      seance_id: string;
      /**
       * Categorie Id
       * Format: uuid
       * @description Catégorie de places tarifée de la séance (Catalogue), pour le prix de la ligne.
       */
      categorie_id: string;
      /**
       * Commande Id
       * Format: uuid
       */
      commande_id: string;
      /**
       * Expire Le
       * Format: date-time
       * @description Fin du verrou (réservation ou confirmation) ; la place est libérée ensuite si la commande n'est pas payée.
       */
      expire_le: string;
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
export type Place = components["schemas"]["Place"];
export type PlacePage = components["schemas"]["PlacePage"];
export type VerrouCreation = components["schemas"]["VerrouCreation"];
export type Verrou = components["schemas"]["Verrou"];
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
  listerPlaces: {
    parameters: {
      query: {
        seance_id: string;
        page?: number;
        size?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Page de places de la séance, avec leur disponibilité. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["PlacePage"];
        };
      };
      /** @description Séance absente ou invalide, ou pagination invalide (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Base injoignable (BASE_INDISPONIBLE), ou Redis injoignable ou trop lent, verrou ni posé ni lu (VERROU_INDISPONIBLE). */
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
  verrouillerPlace: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        place_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["VerrouCreation"];
      };
    };
    responses: {
      /** @description Place verrouillée au profit de la commande (verrou posé ou prolongé). */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Verrou"];
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
      /** @description Aucune place avec cet identifiant dans cette séance (SEAT_NOT_FOUND). */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Place verrouillée par une autre commande ou vendue, ou confirmation demandée sans détenir le verrou (SEAT_ALREADY_TAKEN). */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Identifiant ou corps invalide (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Base injoignable (BASE_INDISPONIBLE), ou Redis injoignable ou trop lent, verrou ni posé ni lu (VERROU_INDISPONIBLE). */
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
