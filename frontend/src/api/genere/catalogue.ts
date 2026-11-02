// Fichier généré par `npm run api:gen` depuis services/catalogue/openapi.yaml.
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
  "/api/v1/events": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Rechercher les événements, page par page (route publique)
     * @description Filtres facultatifs et cumulables. q cherche dans le nom et la description ; ville, du et au retiennent les événements qui ont au moins une séance dans cette ville et dans cet intervalle (bornes incluses). Ordre stable par date de création croissante, puis identifiant.
     */
    get: operations["listerEvenements"];
    put?: never;
    /** Créer un événement (scope events:write ; admin) */
    post: operations["creerEvenement"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/events/{evenement_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Lire le détail d'un événement (route publique) */
    get: operations["lireEvenement"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/events/{evenement_id}/shows": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Lister les séances d'un événement avec leurs catégories, page par page (route publique)
     * @description Ordre stable par début croissant, puis identifiant.
     */
    get: operations["listerSeances"];
    put?: never;
    /**
     * Programmer une séance dans un lieu, avec ses catégories de places (scope events:write ; admin)
     * @description Publie ticketing.show.scheduled, qui porte aussi le nom de l'événement, le nom et la ville du lieu.
     */
    post: operations["creerSeance"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/events/{evenement_id}/shows/{seance_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Lire une séance avec ses catégories de places (route publique) */
    get: operations["lireSeance"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/shows/{seance_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Lire une séance par son seul identifiant, avec ses catégories de places (route publique)
     * @description Utilisée notamment par Commandes, qui ne connaît que la séance de la commande.
     */
    get: operations["lireSeanceParId"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/venues": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Lister les lieux, page par page (route publique)
     * @description Ordre stable par date de création croissante, puis identifiant.
     */
    get: operations["listerLieux"];
    put?: never;
    /** Créer un lieu (scope events:write ; admin) */
    post: operations["creerLieu"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/venues/{lieu_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Lire un lieu (route publique) */
    get: operations["lireLieu"];
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
    /** EvenementCreation */
    EvenementCreation: {
      /** Nom */
      nom: string;
      /** Description */
      description: string;
    };
    /** Evenement */
    Evenement: {
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Nom */
      nom: string;
      /** Description */
      description: string;
      /**
       * Cree Le
       * Format: date-time
       */
      cree_le: string;
    };
    /** EvenementPage */
    EvenementPage: {
      /** Elements */
      elements: components["schemas"]["Evenement"][];
      /** Page */
      page: number;
      /** Size */
      size: number;
      /**
       * Total
       * @description Nombre total d'événements qui répondent aux filtres.
       */
      total: number;
    };
    /** CategorieCreation */
    CategorieCreation: {
      /** Nom */
      nom: string;
      /**
       * Prix
       * @description Prix d'une place de la catégorie, en centimes.
       */
      prix: number;
      /**
       * Rangs
       * @description Rangs de la catégorie ; un rang n'apparaît qu'une fois dans la séance, ni en double dans la catégorie ni dans une autre catégorie (sinon ROW_ALREADY_ASSIGNED).
       */
      rangs: components["schemas"]["Rang"][];
    };
    /** Rang */
    Rang: {
      /** Rang */
      rang: string;
      /**
       * Nombre Places
       * @description Places numérotées de 1 à nombre_places dans le rang.
       */
      nombre_places: number;
    };
    /** Categorie */
    Categorie: {
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Nom */
      nom: string;
      /**
       * Prix
       * @description Prix d'une place de la catégorie, en centimes.
       */
      prix: number;
      /** Rangs */
      rangs: components["schemas"]["Rang"][];
    };
    /** SeanceCreation */
    SeanceCreation: {
      /**
       * Lieu Id
       * Format: uuid
       */
      lieu_id: string;
      /**
       * Debut
       * Format: date-time
       * @description Doit être dans le futur (sinon SHOW_START_IN_PAST).
       */
      debut: string;
      /**
       * Categories
       * @description Catégories de places tarifées de la séance.
       */
      categories: components["schemas"]["CategorieCreation"][];
    };
    /** Seance */
    Seance: {
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /**
       * Evenement Id
       * Format: uuid
       */
      evenement_id: string;
      /**
       * Lieu Id
       * Format: uuid
       */
      lieu_id: string;
      /**
       * Debut
       * Format: date-time
       */
      debut: string;
      /**
       * Annulee
       * @description Vrai une fois la séance annulée (ticketing.show.cancelled publié).
       */
      annulee: boolean;
      /** Categories */
      categories: components["schemas"]["Categorie"][];
    };
    /** SeancePage */
    SeancePage: {
      /** Elements */
      elements: components["schemas"]["Seance"][];
      /** Page */
      page: number;
      /** Size */
      size: number;
      /**
       * Total
       * @description Nombre total de séances de l'événement.
       */
      total: number;
    };
    /** LieuCreation */
    LieuCreation: {
      /** Nom */
      nom: string;
      /** Adresse */
      adresse: string;
      /** Ville */
      ville: string;
    };
    /** Lieu */
    Lieu: {
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Nom */
      nom: string;
      /** Adresse */
      adresse: string;
      /** Ville */
      ville: string;
      /**
       * Cree Le
       * Format: date-time
       */
      cree_le: string;
    };
    /** LieuPage */
    LieuPage: {
      /** Elements */
      elements: components["schemas"]["Lieu"][];
      /** Page */
      page: number;
      /** Size */
      size: number;
      /**
       * Total
       * @description Nombre total de lieux.
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
export type EvenementCreation = components["schemas"]["EvenementCreation"];
export type Evenement = components["schemas"]["Evenement"];
export type EvenementPage = components["schemas"]["EvenementPage"];
export type CategorieCreation = components["schemas"]["CategorieCreation"];
export type Rang = components["schemas"]["Rang"];
export type Categorie = components["schemas"]["Categorie"];
export type SeanceCreation = components["schemas"]["SeanceCreation"];
export type Seance = components["schemas"]["Seance"];
export type SeancePage = components["schemas"]["SeancePage"];
export type LieuCreation = components["schemas"]["LieuCreation"];
export type Lieu = components["schemas"]["Lieu"];
export type LieuPage = components["schemas"]["LieuPage"];
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
  listerEvenements: {
    parameters: {
      query?: {
        q?: string | null;
        ville?: string | null;
        du?: string | null;
        au?: string | null;
        page?: number;
        size?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Page d'événements (depuis le cache Redis si la base ne répond pas). */
      200: {
        headers: {
          /** @description Présent, valeur true, seulement quand la réponse vient du cache Redis parce que la base ne répond pas (mode dégradé) ; absent sinon. */
          "X-Cache-Stale"?: "true";
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["EvenementPage"];
        };
      };
      /** @description Filtres ou pagination invalides, ou du postérieur à au (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Base injoignable et données absentes du cache (BASE_INDISPONIBLE). */
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
  creerEvenement: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["EvenementCreation"];
      };
    };
    responses: {
      /** @description Événement créé. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Evenement"];
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
      /** @description Corps invalide (REQUETE_INVALIDE). */
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
  lireEvenement: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        evenement_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Détail de l'événement (depuis le cache Redis si la base ne répond pas). */
      200: {
        headers: {
          /** @description Présent, valeur true, seulement quand la réponse vient du cache Redis parce que la base ne répond pas (mode dégradé) ; absent sinon. */
          "X-Cache-Stale"?: "true";
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Evenement"];
        };
      };
      /** @description Aucun événement avec cet identifiant (EVENT_NOT_FOUND). */
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
      /** @description Base injoignable et donnée absente du cache (BASE_INDISPONIBLE). */
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
  listerSeances: {
    parameters: {
      query?: {
        page?: number;
        size?: number;
      };
      header?: never;
      path: {
        evenement_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Page de séances (depuis le cache Redis si la base ne répond pas). */
      200: {
        headers: {
          /** @description Présent, valeur true, seulement quand la réponse vient du cache Redis parce que la base ne répond pas (mode dégradé) ; absent sinon. */
          "X-Cache-Stale"?: "true";
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SeancePage"];
        };
      };
      /** @description Aucun événement avec cet identifiant (EVENT_NOT_FOUND). */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Identifiant ou paramètres de pagination invalides (REQUETE_INVALIDE). */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Base injoignable et données absentes du cache (BASE_INDISPONIBLE). */
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
  creerSeance: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        evenement_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["SeanceCreation"];
      };
    };
    responses: {
      /** @description Séance créée. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Seance"];
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
      /** @description Événement ou lieu inconnu (EVENT_NOT_FOUND, VENUE_NOT_FOUND). */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/problem+json": components["schemas"]["Probleme"];
        };
      };
      /** @description Identifiant ou corps invalide (REQUETE_INVALIDE), début dans le passé (SHOW_START_IN_PAST) ou même rang deux fois dans la séance, dans une même catégorie ou dans deux (ROW_ALREADY_ASSIGNED). */
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
  lireSeance: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        evenement_id: string;
        seance_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Séance (depuis le cache Redis si la base ne répond pas). */
      200: {
        headers: {
          /** @description Présent, valeur true, seulement quand la réponse vient du cache Redis parce que la base ne répond pas (mode dégradé) ; absent sinon. */
          "X-Cache-Stale"?: "true";
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Seance"];
        };
      };
      /** @description Événement ou séance inconnu (EVENT_NOT_FOUND, SHOW_NOT_FOUND). */
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
      /** @description Base injoignable et donnée absente du cache (BASE_INDISPONIBLE). */
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
  lireSeanceParId: {
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
      /** @description Séance (depuis le cache Redis si la base ne répond pas). */
      200: {
        headers: {
          /** @description Présent, valeur true, seulement quand la réponse vient du cache Redis parce que la base ne répond pas (mode dégradé) ; absent sinon. */
          "X-Cache-Stale"?: "true";
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Seance"];
        };
      };
      /** @description Aucune séance avec cet identifiant (SHOW_NOT_FOUND). */
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
      /** @description Base injoignable et donnée absente du cache (BASE_INDISPONIBLE). */
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
  listerLieux: {
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
      /** @description Page de lieux (depuis le cache Redis si la base ne répond pas). */
      200: {
        headers: {
          /** @description Présent, valeur true, seulement quand la réponse vient du cache Redis parce que la base ne répond pas (mode dégradé) ; absent sinon. */
          "X-Cache-Stale"?: "true";
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["LieuPage"];
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
      /** @description Base injoignable et données absentes du cache (BASE_INDISPONIBLE). */
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
  creerLieu: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["LieuCreation"];
      };
    };
    responses: {
      /** @description Lieu créé. */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Lieu"];
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
      /** @description Corps invalide (REQUETE_INVALIDE). */
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
  lireLieu: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        lieu_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Lieu (depuis le cache Redis si la base ne répond pas). */
      200: {
        headers: {
          /** @description Présent, valeur true, seulement quand la réponse vient du cache Redis parce que la base ne répond pas (mode dégradé) ; absent sinon. */
          "X-Cache-Stale"?: "true";
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Lieu"];
        };
      };
      /** @description Aucun lieu avec cet identifiant (VENUE_NOT_FOUND). */
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
      /** @description Base injoignable et donnée absente du cache (BASE_INDISPONIBLE). */
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
