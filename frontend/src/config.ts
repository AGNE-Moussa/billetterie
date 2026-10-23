// URL des services lues dans les variables Vite (VITE_API_URL, VITE_KEYCLOAK_URL).
// Par défaut des chemins relatifs : le front, l'API et Keycloak partagent le même domaine
// derrière Traefik. Une variable vide compte comme absente.

const URL_API_PAR_DEFAUT = "/api";
const URL_KEYCLOAK_PAR_DEFAUT = "/auth";

/** URL de base de l'API (VITE_API_URL), sinon `/api`. */
export function urlApi(): string {
  return import.meta.env.VITE_API_URL || URL_API_PAR_DEFAUT;
}

/** URL de base de Keycloak (VITE_KEYCLOAK_URL), sinon `/auth`. */
export function urlKeycloak(): string {
  return import.meta.env.VITE_KEYCLOAK_URL || URL_KEYCLOAK_PAR_DEFAUT;
}
