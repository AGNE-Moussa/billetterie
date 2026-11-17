// Outils du plan de salle (E03) et du paiement (E04) : rangs ordonnés, libellés de place,
// sélection gardée dans l'URL (`?places=id1,id2`, docs/front/routes.md).
import type { Place } from "../../api/genere/billets";
import type { Categorie } from "../../api/genere/catalogue";

/** Places par commande au plus (`maxItems` de `CommandeCreation.place_ids`). */
export const PLACES_PAR_COMMANDE_MAX = 10;

export interface RangPlan {
  rang: string;
  places: Place[];
}

/** Places groupées par rang, dans l'ordre de l'API (rang puis numéro). */
export function rangsDuPlan(places: readonly Place[]): RangPlan[] {
  const rangs: RangPlan[] = [];
  const parRang = new Map<string, RangPlan>();
  for (const place of places) {
    let rang = parRang.get(place.rang);
    if (rang === undefined) {
      rang = { rang: place.rang, places: [] };
      parRang.set(place.rang, rang);
      rangs.push(rang);
    }
    rang.places.push(place);
  }
  for (const rang of rangs) {
    rang.places.sort((a, b) => a.numero - b.numero);
  }
  return rangs;
}

/** Catégories de la séance par identifiant. */
export function categoriesParId(categories: readonly Categorie[]): Map<string, Categorie> {
  return new Map(categories.map((categorie) => [categorie.id, categorie]));
}

/** « Rang B, place 12 ». */
export function libellePlace(place: Pick<Place, "rang" | "numero">): string {
  return `Rang ${place.rang}, place ${String(place.numero)}`;
}

/** « B12 », forme courte du récapitulatif. */
export function libelleCourt(place: Pick<Place, "rang" | "numero">): string {
  return `${place.rang}${String(place.numero)}`;
}

/** Clé de requête des places d'une séance (E03, et E04 pour les libellés). */
export function clePlaces(seanceId: string) {
  return ["billets", "places", seanceId] as const;
}

/** Clé de requête d'une commande (posée par E03, lue par E04). */
export function cleCommande(commandeId: string) {
  return ["commandes", "commande", commandeId] as const;
}

const PARAMETRE_PLACES = "places";

/** Identifiants de la sélection lus dans l'URL, sans doublon, bornés au maximum. */
export function lireSelection(parametres: URLSearchParams): string[] {
  const brut = parametres.get(PARAMETRE_PLACES) ?? "";
  const ids = brut
    .split(",")
    .map((id) => id.trim())
    .filter((id) => id !== "");
  return [...new Set(ids)].slice(0, PLACES_PAR_COMMANDE_MAX);
}

/** Paramètres d'URL avec la sélection (paramètre retiré si elle est vide). */
export function avecSelection(
  parametres: URLSearchParams,
  ids: readonly string[],
): URLSearchParams {
  const suivants = new URLSearchParams(parametres);
  if (ids.length > 0) suivants.set(PARAMETRE_PLACES, ids.join(","));
  else suivants.delete(PARAMETRE_PLACES);
  return suivants;
}
