// Fichier généré par `npm run api:gen` : un import par contrat services/*/openapi.yaml.
// Ne pas modifier à la main : ajouter le contrat puis relancer la génération.

import type { paths as CheminsBillets } from "./billets";
import type { paths as CheminsCatalogue } from "./catalogue";
import type { paths as CheminsCommandes } from "./commandes";
import type { paths as CheminsEcho } from "./echo";
import type { paths as CheminsNotifications } from "./notifications";
import type { paths as CheminsPaiements } from "./paiements";

/** Chemins de tous les contrats (les `paths` de chaque service, réunis). */
export type CheminsApi = CheminsBillets &
  CheminsCatalogue &
  CheminsCommandes &
  CheminsEcho &
  CheminsNotifications &
  CheminsPaiements;
