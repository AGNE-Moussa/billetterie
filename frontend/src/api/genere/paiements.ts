// Fichier généré par `npm run api:gen` depuis services/paiements/openapi.yaml.
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
  "/api/v1/payments": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Payer une commande en mode test (scope payments:write ; client services seulement)
     * @description Paiement simulé, aucune donnée de carte réelle ; le numéro de carte n'est ni journalisé ni conservé. Un seul paiement par commande. Idempotent par Idempotency-Key (égal à commande_id) ; une requête rejouée à l'identique renvoie le résultat enregistré (201 ou 402), sans nouveau paiement.
     */
    post: operations["creerPaiement"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/payments/{commande_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Lire le paiement d'une commande (scope payments:write ; client services seulement)
     * @description Lecture sans effet, utilisée par Commandes avant d'expirer une commande déjà envoyée à Paiements, pour savoir si un remboursement est dû ; ne crée jamais de paiement.
     */
    get: operations["lirePaiement"];
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
    /** PaiementCreation */
    PaiementCreation: {
      /**
       * Commande Id
       * Format: uuid
       */
      commande_id: string;
      /**
       * Seance Id
       * Format: uuid
       * @description Séance de la commande ; Paiements consomme ticketing.show.cancelled et rembourse les paiements ACCEPTE de la séance.
       */
      seance_id: string;
      /**
       * Montant
       * @description Montant en centimes.
       */
      montant: number;
      /**
       * Carte Test
       * @description Numéro de carte du paiement simulé, jamais journalisé. Numéros de test : 4000000000000002 refusé (PAYMENT_REFUSED), tout autre numéro de 16 chiffres accepté (par exemple 4242424242424242).
       */
      carte_test: string;
    };
    /**
     * StatutPaiement
     * @enum {string}
     */
    StatutPaiement: "ACCEPTE" | "REFUSE" | "REMBOURSE";
    /** Paiement */
    Paiement: {
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
       * @description Séance de la commande ; Paiements consomme ticketing.show.cancelled et rembourse les paiements ACCEPTE de la séance.
       */
      seance_id: string;
      /**
       * Montant
       * @description Montant en centimes.
       */
      montant: number;
      statut: components["schemas"]["StatutPaiement"];
      /**
       * Cree Le
       * Format: date-time
       */
      cree_le: string;
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
export type PaiementCreation = components["schemas"]["PaiementCreation"];
export type StatutPaiement = components["schemas"]["StatutPaiement"];
export type Paiement = components["schemas"]["Paiement"];
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
  creerPaiement: {
    parameters: {
      query?: never;
      header: {
        /** @description Identifiant de la commande payée (même valeur que commande_id). */
        "Idempotency-Key": string;
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["PaiementCreation"];
      };
    };
    responses: {
      /** @description Paiement accepté (statut ACCEPTE). */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Paiement"];
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
      /** @description Paiement refusé, enregistré avec le statut REFUSE (PAYMENT_REFUSED). */
      402: {
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
      /** @description Un paiement différent existe déjà pour cette commande (PAYMENT_ALREADY_EXISTS), ou la séance est annulée d'après la projection des séances annulées (SHOW_CANCELLED). */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description En-tête ou corps invalide, ou Idempotency-Key différent de commande_id (REQUETE_INVALIDE). */
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
  lirePaiement: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        commande_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Paiement de la commande. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Paiement"];
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
      /** @description Aucun paiement pour cette commande (PAYMENT_NOT_FOUND). */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Paramètre de chemin invalide (REQUETE_INVALIDE). */
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
