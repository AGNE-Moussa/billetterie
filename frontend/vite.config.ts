// Vite (dev et build) et Vitest (tests de composant sous jsdom).
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/",
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    // 5 s par défaut : trop court quand la plateforme Docker occupe le poste (rendus complets
    // de main.test.tsx, minuteries de FournisseurAuthentification) ; un test lent reste signalé.
    testTimeout: 15000,
    setupFiles: ["./src/setupTests.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
