// Chargé par Vitest avant chaque fichier de test : matchers DOM (toBeInTheDocument, ...) et
// serveur MSW (API et Keycloak simulés). Toute requête sans gestionnaire fait échouer le test.
import "@testing-library/jest-dom/vitest";

import { serveurMsw } from "./mocks/serveur";

beforeAll(() => {
  serveurMsw.listen({ onUnhandledFrame: "error" });
});

afterEach(() => {
  serveurMsw.resetHandlers();
});

afterAll(() => {
  serveurMsw.close();
});
