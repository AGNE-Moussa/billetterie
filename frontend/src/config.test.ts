// Cas composant de BIL-F26 (E3) : URL des services lues dans VITE_API_URL et VITE_KEYCLOAK_URL,
// par défaut les chemins relatifs /api et /auth.
import { urlApi, urlKeycloak } from "./config";

afterEach(() => {
  vi.unstubAllEnvs();
});

it.each([
  { variable: "VITE_API_URL", lire: urlApi, attendu: "/api" },
  { variable: "VITE_KEYCLOAK_URL", lire: urlKeycloak, attendu: "/auth" },
])(
  "test_sans_variable_les_urls_sont_les_chemins_relatifs_api_et_auth ($variable)",
  ({ variable, lire, attendu }) => {
    vi.stubEnv(variable, undefined);

    expect(lire()).toBe(attendu);
  },
);

it.each([
  {
    variable: "VITE_API_URL",
    lire: urlApi,
    valeur: "http://api.exemple.test/api",
  },
  {
    variable: "VITE_KEYCLOAK_URL",
    lire: urlKeycloak,
    valeur: "http://auth.exemple.test/auth",
  },
])(
  "test_une_variable_definie_remplace_le_chemin_par_defaut ($variable)",
  ({ variable, lire, valeur }) => {
    vi.stubEnv(variable, valeur);

    expect(lire()).toBe(valeur);
  },
);
