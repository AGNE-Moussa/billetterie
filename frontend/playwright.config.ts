// Parcours de bout en bout, joués contre la plateforme démarrée par `make up` (Traefik sur :80).
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  // Un seul worker : les parcours partagent la plateforme et les comptes de test, et deux
  // connexions simultanées du même compte déclenchent l'anti force brute de Keycloak (BIL-F27).
  workers: 1,
  use: {
    baseURL: "http://localhost",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
