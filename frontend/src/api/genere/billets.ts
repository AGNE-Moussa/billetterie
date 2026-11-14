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
  "/api/v1/tickets": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Lister mes billets, page par page (scope tickets:read ; client et revendeur)
     * @description Filtré par l'appelant du jeton, jamais par un paramètre ; commande_id, s'il est fourni, restreint en plus aux billets de cette commande (une commande inconnue ou d'un autre appelant répond 200 avec elements vide). Ordre stable par date d'émission décroissante, puis identifiant.
     */
    get: operations["listerBillets"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/tickets/{billet_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Lire un de mes billets, avec son QR code (scope tickets:read ; client et revendeur)
     * @description Un billet d'un autre appelant répond 404 TICKET_NOT_FOUND, comme un billet inexistant, jamais 403.
     */
    get: operations["lireBillet"];
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
    /**
     * StatutBillet
     * @description ANNULE quand la séance est annulée (consommateur de ticketing.show.cancelled).
     * @enum {string}
     */
    StatutBillet: "EMIS" | "ANNULE";
    /** Billet */
    Billet: {
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /**
       * Commande Id
       * Format: uuid
       */
      commande_id: string;
      /**
       * Seance Id
       * Format: uuid
       */
      seance_id: string;
      /**
       * Place Id
       * Format: uuid
       */
      place_id: string;
      /**
       * Rang
       * @description Rang de la place (table places).
       */
      rang: string;
      /**
       * Numero
       * @description Numéro de la place dans son rang (table places).
       */
      numero: number;
      statut: components["schemas"]["StatutBillet"];
      /**
       * Qr Code
       * @description Identifiant du billet signé (HMAC), jamais de donnée lisible.
       */
      qr_code: string;
      /**
       * Emis Le
       * Format: date-time
       */
      emis_le: string;
    };
    /** BilletPage */
    BilletPage: {
      /** Elements */
      elements: components["schemas"]["Billet"][];
      /** Page */
      page: number;
      /** Size */
      size: number;
      /**
       * Total
       * @description Nombre total de billets de l'appelant (de la commande si commande_id est fourni).
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
export type Place = components["schemas"]["Place"];
export type PlacePage = components["schemas"]["PlacePage"];
export type VerrouCreation = components["schemas"]["VerrouCreation"];
export type Verrou = components["schemas"]["Verrou"];
export type StatutBillet = components["schemas"]["StatutBillet"];
export type Billet = components["schemas"]["Billet"];
export type BilletPage = components["schemas"]["BilletPage"];
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
  listerBillets: {
    parameters: {
      query?: {
        commande_id?: string | null;
        page?: number;
        size?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Page des billets de l'appelant. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["BilletPage"];
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
      /** @description Identifiant de commande ou paramètres de pagination invalides (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Base injoignable (BASE_INDISPONIBLE). */
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
  lireBillet: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        billet_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Billet de l'appelant. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Billet"];
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
      /** @description Aucun billet de l'appelant avec cet identifiant (TICKET_NOT_FOUND). */
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
      /** @description Base injoignable (BASE_INDISPONIBLE). */
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
