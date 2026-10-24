// Configuration oidc-client-ts de l'application : client Keycloak public `frontend`,
// Authorization Code + PKCE, utilisateur en mémoire, état temporaire en sessionStorage.
import {
  InMemoryWebStorage,
  UserManager,
  WebStorageStateStore,
  type UserManagerSettings,
} from "oidc-client-ts";

import { urlKeycloak } from "../config";

/** Chemin de la page de rappel OIDC (`redirect_uri`). */
export const CHEMIN_RAPPEL = "/connexion/rappel";

/**
 * Chemin de retour de la reconnexion silencieuse (iframe, `prompt=none`) : main.tsx n'y monte
 * pas l'application, il transmet seulement la réponse à la fenêtre parente.
 */
export const CHEMIN_RAPPEL_SILENCIEUX = "/connexion/silencieux";

/** Renouvellement du jeton d'accès 60 s avant son expiration. */
const PREAVIS_EXPIRATION_EN_SECONDES = 60;

/** Autorité du realm : origine + `urlKeycloak()` + `/realms/billetterie`. */
function autorite(origine: string): string {
  const base = new URL(urlKeycloak(), origine).href.replace(/\/+$/, "");
  return `${base}/realms/billetterie`;
}

/** Paramètres du `UserManager` de l'application. */
export function parametresOidc(): UserManagerSettings {
  const origine = window.location.origin;
  return {
    authority: autorite(origine),
    // Client public : aucun secret côté navigateur ; PKCE S256 imposé par oidc-client-ts.
    client_id: "frontend",
    response_type: "code",
    scope: "openid profile",
    redirect_uri: `${origine}${CHEMIN_RAPPEL}`,
    silent_redirect_uri: `${origine}${CHEMIN_RAPPEL_SILENCIEUX}`,
    post_logout_redirect_uri: `${origine}/`,
    // Jetons en mémoire seulement ; seul l'état de la redirection (state, code_verifier) va en
    // sessionStorage, le temps de l'aller-retour vers Keycloak.
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: true,
    accessTokenExpiringNotificationTimeInSeconds: PREAVIS_EXPIRATION_EN_SECONDES,
    loadUserInfo: false,
    monitorSession: false,
  };
}

/** `UserManager` configuré comme l'application (utilisé par défaut par le fournisseur). */
export function creerUserManager(): UserManager {
  return new UserManager(parametresOidc());
}
