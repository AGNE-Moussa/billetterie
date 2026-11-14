// Filtres du catalogue (E01) gardés dans l'URL (`?q=&ville=&du=&au=&page=`) : lien partageable
// et bouton retour du navigateur cohérent (CA1 de BIL-019). Les dates de l'URL sont des jours
// (`AAAA-MM-JJ`, valeur d'un champ date) ; l'API attend des dates-heures ISO 8601 avec fuseau.
import type { FiltresEvenements } from "../../api/catalogue";

export interface FiltresCatalogue {
  q: string;
  ville: string;
  /** Premier jour, `AAAA-MM-JJ` ; vide : aucune borne. */
  du: string;
  /** Dernier jour (inclus), `AAAA-MM-JJ` ; vide : aucune borne. */
  au: string;
}

export const FILTRES_VIDES: FiltresCatalogue = { q: "", ville: "", du: "", au: "" };

const CLES_FILTRES = ["q", "ville", "du", "au"] as const;

const JOUR = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Filtres lus dans l'URL ; un paramètre absent vaut chaîne vide. */
export function lireFiltres(parametres: URLSearchParams): FiltresCatalogue {
  return {
    q: parametres.get("q")?.trim() ?? "",
    ville: parametres.get("ville")?.trim() ?? "",
    du: parametres.get("du") ?? "",
    au: parametres.get("au") ?? "",
  };
}

/** Numéro de page lu dans l'URL ; absent ou illisible : 1. */
export function lirePage(parametres: URLSearchParams): number {
  const valeur = Number(parametres.get("page"));
  return Number.isInteger(valeur) && valeur >= 1 ? valeur : 1;
}

export function filtresActifs(filtres: FiltresCatalogue): boolean {
  return CLES_FILTRES.some((cle) => filtres[cle] !== "");
}

/** Paramètres d'URL des filtres (vides omis) et de la page (omise si 1). */
export function versParametres(filtres: FiltresCatalogue, page = 1): URLSearchParams {
  const parametres = new URLSearchParams();
  for (const cle of CLES_FILTRES) {
    const valeur = filtres[cle].trim();
    if (valeur !== "") {
      parametres.set(cle, valeur);
    }
  }
  if (page > 1) {
    parametres.set("page", String(page));
  }
  return parametres;
}

/**
 * Jour `AAAA-MM-JJ` converti en date-heure ISO à l'heure locale donnée ; une valeur qui n'est pas
 * un jour est transmise telle quelle (l'API la refuse en 422 REQUETE_INVALIDE, affiché à l'écran).
 */
function versDateHeure(jour: string, finDeJournee: boolean): string {
  const correspondance = JOUR.exec(jour);
  if (correspondance === null) {
    return jour;
  }
  const [, annee, mois, quantieme] = correspondance.map(Number);
  const date = finDeJournee
    ? new Date(annee ?? 0, (mois ?? 1) - 1, quantieme, 23, 59, 59, 999)
    : new Date(annee ?? 0, (mois ?? 1) - 1, quantieme, 0, 0, 0, 0);
  return Number.isNaN(date.getTime()) ? jour : date.toISOString();
}

/** Paramètres de `listerEvenements` : `du` au début du jour, `au` à la fin du jour (inclus). */
export function versRequete(filtres: FiltresCatalogue, page: number): FiltresEvenements {
  const requete: FiltresEvenements = { page };
  if (filtres.q !== "") requete.q = filtres.q;
  if (filtres.ville !== "") requete.ville = filtres.ville;
  if (filtres.du !== "") requete.du = versDateHeure(filtres.du, false);
  if (filtres.au !== "") requete.au = versDateHeure(filtres.au, true);
  return requete;
}
