// Serveur MSW des tests de composant (Vitest, Node) : aucun gestionnaire par défaut, chaque
// test déclare les siens avec `serveurMsw.use(...)`. Démarré et remis à zéro par setupTests.ts.
import { setupServer } from "msw/node";

export const serveurMsw = setupServer();
