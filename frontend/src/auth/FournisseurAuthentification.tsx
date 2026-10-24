// Fournisseur d'authentification : connexion, déconnexion, reconnexion et renouvellement
// silencieux ; jetons gardés en mémoire. Le `UserManager` est injectable (tests).
import type { User, UserManager } from "oidc-client-ts";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";

import { brancherSourceJeton, type SourceJeton } from "../api/client";
import { CHEMIN_RAPPEL, creerUserManager } from "./configurationOidc";
import { rolesDuJeton } from "./roles";
import { ContexteSession, type Session, type StatutSession } from "./session";

export interface ProprietesFournisseurAuthentification {
  /** `UserManager` à utiliser ; par défaut celui de `creerUserManager()`. */
  userManager?: UserManager;
  children: ReactNode;
}

interface EtatSession {
  statut: StatutSession;
  utilisateur: User | null;
  sessionExpiree: boolean;
}

const ETAT_INITIAL: EtatSession = {
  statut: "chargement",
  utilisateur: null,
  sessionExpiree: false,
};

/** Page rouverte après le rappel : un chemin interne de l'application, sinon l'accueil. */
function pageDeRetour(etat: unknown): string {
  if (typeof etat !== "object" || etat === null) {
    return "/";
  }
  const page = (etat as { pageDeRetour?: unknown }).pageDeRetour;
  return typeof page === "string" ? cheminInterne(page) : "/";
}

/**
 * Chemin normalisé (`pathname + search + hash`) de `chemin` résolu contre l'origine de
 * l'application ; l'accueil si la résolution échoue, sort de l'origine (`//…`, `/\…`,
 * caractères de contrôle retirés par l'analyseur d'URL, URL absolue), vise la page de rappel
 * ou donne un chemin résolu commençant par `//` (`/.//…`, `/%2e//…`, `/x/..//…`) : rendu tel
 * quel, ce chemin serait une URL relative au protocole, donc hors de l'application. Le
 * contrôle porte sur le chemin déjà résolu : un seul passage suffit.
 */
export function cheminInterne(chemin: string): string {
  const origine = window.location.origin;
  let adresse: URL;
  try {
    adresse = new URL(chemin, origine);
  } catch {
    return "/";
  }
  if (
    adresse.origin !== origine ||
    adresse.pathname.startsWith("//") ||
    adresse.pathname.startsWith(CHEMIN_RAPPEL)
  ) {
    return "/";
  }
  return `${adresse.pathname}${adresse.search}${adresse.hash}`;
}

export function FournisseurAuthentification({
  userManager: userManagerInjecte,
  children,
}: ProprietesFournisseurAuthentification) {
  const [userManager] = useState(() => userManagerInjecte ?? creerUserManager());
  const [etat, setEtat] = useState<EtatSession>(ETAT_INITIAL);
  // Copie synchrone de l'utilisateur pour le client d'API (lue hors du rendu React).
  const utilisateurCourant = useRef<User | null>(null);
  const renouvellementEnCours = useRef<Promise<string | null> | null>(null);
  const demarrageLance = useRef(false);
  const { pathname } = useLocation();

  const appliquer = useCallback((utilisateur: User) => {
    utilisateurCourant.current = utilisateur;
    setEtat({ statut: "connecte", utilisateur, sessionExpiree: false });
  }, []);

  const oublier = useCallback((sessionExpiree?: boolean) => {
    utilisateurCourant.current = null;
    setEtat((precedent) => ({
      statut: "non-connecte",
      utilisateur: null,
      sessionExpiree: sessionExpiree ?? precedent.sessionExpiree,
    }));
  }, []);

  /** Échec du renouvellement : utilisateur oublié, « Votre session a expiré ». */
  const expirer = useCallback(async () => {
    oublier(true);
    try {
      await userManager.removeUser();
    } catch {
      // L'utilisateur est déjà oublié côté fournisseur.
    }
  }, [oublier, userManager]);

  // Événements du UserManager et branchement du client d'API sur le jeton en mémoire.
  useEffect(() => {
    const surChargement = (utilisateur: User) => appliquer(utilisateur);
    const surDechargement = () => oublier();
    const surErreurRenouvellement = () => {
      void expirer();
    };
    userManager.events.addUserLoaded(surChargement);
    userManager.events.addUserUnloaded(surDechargement);
    userManager.events.addSilentRenewError(surErreurRenouvellement);

    const source: SourceJeton = {
      jetonAcces: () => utilisateurCourant.current?.access_token ?? null,
      renouveler: () => {
        // Un seul renouvellement à la fois, partagé par les requêtes refusées en même temps.
        renouvellementEnCours.current ??= userManager
          .signinSilent()
          .then(
            (utilisateur) => utilisateur?.access_token ?? null,
            async () => {
              await expirer();
              return null;
            },
          )
          .finally(() => {
            renouvellementEnCours.current = null;
          });
        return renouvellementEnCours.current;
      },
    };
    brancherSourceJeton(source);

    return () => {
      userManager.events.removeUserLoaded(surChargement);
      userManager.events.removeUserUnloaded(surDechargement);
      userManager.events.removeSilentRenewError(surErreurRenouvellement);
      brancherSourceJeton(null);
    };
  }, [userManager, appliquer, oublier, expirer]);

  // Démarrage : utilisateur déjà en mémoire, sinon reconnexion silencieuse. Sur la page de
  // rappel, c'est elle qui termine la connexion.
  useEffect(() => {
    if (demarrageLance.current) {
      return;
    }
    demarrageLance.current = true;
    if (pathname === CHEMIN_RAPPEL) {
      return;
    }
    void (async () => {
      try {
        const existant = await userManager.getUser();
        if (existant !== null && !existant.expired) {
          appliquer(existant);
          return;
        }
        const retrouve = await userManager.signinSilent();
        if (retrouve !== null) {
          appliquer(retrouve);
        } else {
          oublier();
        }
      } catch {
        // Aucune session Keycloak à retrouver (login_required, Keycloak injoignable).
        if (utilisateurCourant.current === null) {
          oublier();
        }
      }
    })();
  }, [userManager, pathname, appliquer, oublier]);

  const seConnecter = useCallback(
    async (page?: string) => {
      const retour = page === undefined ? "/" : cheminInterne(page);
      try {
        await userManager.signinRedirect({ state: { pageDeRetour: retour } });
        return true;
      } catch {
        // Keycloak injoignable : l'utilisateur reste non connecté et peut réessayer.
        return false;
      }
    },
    [userManager],
  );

  const seDeconnecter = useCallback(async () => {
    setEtat((precedent) => ({ ...precedent, sessionExpiree: false }));
    try {
      // Retire l'utilisateur (événement userUnloaded), puis quitte la page vers Keycloak.
      await userManager.signoutRedirect();
    } catch {
      oublier();
    }
  }, [userManager, oublier]);

  const terminerConnexion = useCallback(
    async (adresseRappel: string) => {
      try {
        const utilisateur = await userManager.signinRedirectCallback(adresseRappel);
        appliquer(utilisateur);
        return pageDeRetour(utilisateur.state);
      } catch (erreur) {
        oublier();
        throw erreur;
      }
    },
    [userManager, appliquer, oublier],
  );

  const session = useMemo<Session>(() => {
    const { utilisateur } = etat;
    const nom = utilisateur?.profile.preferred_username;
    return {
      statut: etat.statut,
      utilisateur,
      nomUtilisateur: typeof nom === "string" ? nom : null,
      roles: utilisateur === null ? [] : rolesDuJeton(utilisateur.access_token),
      sessionExpiree: etat.sessionExpiree,
      seConnecter,
      seDeconnecter,
      terminerConnexion,
    };
  }, [etat, seConnecter, seDeconnecter, terminerConnexion]);

  return <ContexteSession.Provider value={session}>{children}</ContexteSession.Provider>;
}
