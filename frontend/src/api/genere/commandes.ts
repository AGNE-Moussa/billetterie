// Fichier généré par `npm run api:gen` depuis services/commandes/openapi.yaml.
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
  "/api/v1/orders": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Lister mes commandes, page par page (scope orders:read ; client et revendeur)
     * @description Filtré par l'appelant du jeton, jamais par un paramètre (règle métier 6). Ordre stable par date de création décroissante, puis identifiant.
     */
    get: operations["listerCommandes"];
    put?: never;
    /**
     * Commander des places d'une séance, et payer si une carte est fournie (scope orders:write ; client et revendeur)
     * @description Crée d'abord la commande EN_ATTENTE, puis verrouille chaque place auprès de Billets en durée de réservation (prix de chaque ligne lu dans la catégorie de la place) ; un échec de verrou passe la commande EXPIREE et publie ticketing.order.expired, qui libère les places déjà verrouillées. Sans carte_test, la commande s'arrête là : 201 EN_ATTENTE, places verrouillées jusqu'à expire_le, aucun appel à Paiements ; elle se paie ensuite par payerCommande. Avec carte_test, juste avant Paiements, les places sont reverrouillées en durée de confirmation ; une place perdue donne 409 SEAT_ALREADY_TAKEN, la commande passe EXPIREE, sans aucun débit. Paiement accepté, la commande est confirmée et ticketing.order.confirmed est publié. La commande appartient à l'appelant du jeton.
     */
    post: operations["creerCommande"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/orders/{commande_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Suivre une de mes commandes (scope orders:read ; client et revendeur) */
    get: operations["lireCommande"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/orders/{commande_id}/payment": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Payer une de mes commandes en attente (scope orders:write ; client et revendeur)
     * @description Premier paiement d'une commande créée sans carte_test, ou nouvel essai après un 503 de Paiements, tant que la commande est EN_ATTENTE (avant expire_le). Juste avant Paiements, les places sont reverrouillées en durée de confirmation ; une place perdue donne 409 SEAT_ALREADY_TAKEN, la commande passe EXPIREE, sans aucun débit. Paiement accepté, la commande est confirmée et ticketing.order.confirmed est publié.
     */
    post: operations["payerCommande"];
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
    /** CommandeCreation */
    CommandeCreation: {
      /**
       * Seance Id
       * Format: uuid
       */
      seance_id: string;
      /** Place Ids */
      place_ids: string[];
      /**
       * Carte Test
       * @description Facultatif. Absent : la commande est créée EN_ATTENTE, places verrouillées jusqu'à expire_le, sans appel à Paiements, et se paie ensuite par payerCommande. Présent : numéro de carte du paiement simulé, transmis à Paiements et jamais journalisé. Numéros de test : 4000000000000002 refusé (PAYMENT_REFUSED), tout autre numéro de 16 chiffres accepté (par exemple 4242424242424242).
       * @default null
       */
      carte_test: string | null;
    };
    /** PaiementCommande */
    PaiementCommande: {
      /**
       * Carte Test
       * @description Numéro de carte du paiement simulé, transmis à Paiements et jamais journalisé. Numéros de test : 4000000000000002 refusé (PAYMENT_REFUSED), tout autre numéro de 16 chiffres accepté (par exemple 4242424242424242).
       */
      carte_test: string;
    };
    /**
     * StatutCommande
     * @description Transitions autorisées : EN_ATTENTE vers CONFIRMEE ou EXPIREE ; CONFIRMEE vers REMBOURSEE ; EXPIREE et REMBOURSEE sont finales. EXPIREE : non payée avant expire_le, paiement refusé, échec de verrou ou place perdue avant paiement, ou séance annulée alors que la commande était EN_ATTENTE (ticketing.show.cancelled). REMBOURSEE : remboursement après ticketing.show.cancelled ou ticketing.ticket.rejected (place refusée à l'émission du billet), reçu par ticketing.payment.refunded.
     * @enum {string}
     */
    StatutCommande: "EN_ATTENTE" | "CONFIRMEE" | "EXPIREE" | "REMBOURSEE";
    /** LigneCommande */
    LigneCommande: {
      /**
       * Place Id
       * Format: uuid
       */
      place_id: string;
      /**
       * Montant
       * @description Prix de la place en centimes (catégorie de la place au moment de la commande).
       */
      montant: number;
    };
    /** Commande */
    Commande: {
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
      /** Lignes */
      lignes: components["schemas"]["LigneCommande"][];
      statut: components["schemas"]["StatutCommande"];
      /**
       * Montant Total
       * @description Somme des montants des lignes, en centimes.
       */
      montant_total: number;
      /**
       * Cree Le
       * Format: date-time
       */
      cree_le: string;
      /**
       * Expire Le
       * Format: date-time
       * @description Fin du plus court des verrous de ses places (réservation de 10 minutes par défaut, configurable ; confirmation de 1 h juste avant Paiements) ; une commande encore EN_ATTENTE à cette date devient EXPIREE.
       */
      expire_le: string;
    };
    /** CommandePage */
    CommandePage: {
      /** Elements */
      elements: components["schemas"]["Commande"][];
      /** Page */
      page: number;
      /** Size */
      size: number;
      /**
       * Total
       * @description Nombre total de commandes de l'appelant.
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
export type CommandeCreation = components["schemas"]["CommandeCreation"];
export type PaiementCommande = components["schemas"]["PaiementCommande"];
export type StatutCommande = components["schemas"]["StatutCommande"];
export type LigneCommande = components["schemas"]["LigneCommande"];
export type Commande = components["schemas"]["Commande"];
export type CommandePage = components["schemas"]["CommandePage"];
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
  listerCommandes: {
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
      /** @description Page des commandes de l'appelant. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["CommandePage"];
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
  creerCommande: {
    parameters: {
      query?: never;
      header?: {
        /** @description Facultatif ; une requête terminée, rejouée avec la même clé par le même appelant, répond 200 avec la commande déjà créée ; rejouée pendant que la première est en cours, elle répond 409 REQUEST_IN_PROGRESS. */
        "Idempotency-Key"?: string | null;
      };
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CommandeCreation"];
      };
    };
    responses: {
      /** @description Rejeu d'une requête terminée avec la même Idempotency-Key par le même appelant ; commande déjà créée. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Commande"];
        };
      };
      /** @description Commande créée. Avec carte_test, payée (statut CONFIRMEE) ; sans carte_test, statut EN_ATTENTE, places verrouillées jusqu'à expire_le, à payer par payerCommande. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Commande"];
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
      /** @description Avec carte_test seulement, paiement refusé ; la commande expire et ses places sont libérées (PAYMENT_REFUSED). */
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
      /** @description Séance inconnue (SHOW_NOT_FOUND) ou place inconnue dans cette séance (SEAT_NOT_FOUND). */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Place déjà prise (SEAT_ALREADY_TAKEN), nombre maximal de billets par séance dépassé pour l'appelant (TICKET_LIMIT_EXCEEDED), séance annulée (SHOW_CANCELLED) ou déjà commencée (SHOW_ALREADY_STARTED), ou requête de même Idempotency-Key encore en cours (REQUEST_IN_PROGRESS). */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description En-tête ou corps invalide (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Base injoignable (BASE_INDISPONIBLE), ou Billets, Catalogue ou Paiements (appelé avec carte_test seulement) indisponible (SERVICE_INDISPONIBLE). Si Paiements ne répond pas, la commande reste EN_ATTENTE, ses places verrouillées jusqu'à expire_le ; elle se retrouve par listerCommandes et se paie par payerCommande. */
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
  lireCommande: {
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
      /** @description Commande de l'appelant. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Commande"];
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
      /** @description Aucune commande de l'appelant avec cet identifiant (ORDER_NOT_FOUND). */
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
  payerCommande: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        commande_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["PaiementCommande"];
      };
    };
    responses: {
      /** @description Commande payée (statut CONFIRMEE). */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Commande"];
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
      /** @description Paiement refusé ; la commande expire et ses places sont libérées (PAYMENT_REFUSED). */
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
      /** @description Aucune commande de l'appelant avec cet identifiant (ORDER_NOT_FOUND), ou séance de la commande inconnue de Catalogue (SHOW_NOT_FOUND). */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description La commande n'est pas EN_ATTENTE (ORDER_NOT_PENDING), sa réservation est encore en cours (REQUEST_IN_PROGRESS), une place est perdue (SEAT_ALREADY_TAKEN ; la commande passe EXPIREE), ou sa séance est annulée (SHOW_CANCELLED) ou déjà commencée (SHOW_ALREADY_STARTED ; la commande passe EXPIREE). Un paiement déjà accepté est signalé à rembourser (ticketing.order.expired, remboursement_du). */
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
      /** @description Base injoignable (BASE_INDISPONIBLE), ou Billets (reverrouillage), Catalogue (lecture de la séance) ou Paiements indisponible, la commande restant EN_ATTENTE jusqu'à expire_le (SERVICE_INDISPONIBLE). */
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
