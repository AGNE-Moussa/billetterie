// Parcours de bout en bout, joués contre la plateforme démarrée par `make up` (Traefik sur :80).
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  use: {
    baseURL: "http://localhost",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
