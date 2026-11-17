// Remplissage d'une séance (E14) calculé côté front sur `listerPlaces` (Q4 de
// docs/front/ecrans.md) : aucune route d'agrégat ; une place indisponible est verrouillée ou
// vendue, l'API ne distingue pas les deux (approximation assumée par le ticket).
import type { Place } from "../../api/genere/billets";
import type { Categorie } from "../../api/genere/catalogue";

export interface LigneRemplissage {
  /** Identifiant de catégorie, ou `total` pour la ligne de synthèse. */
  cle: string;
  libelle: string;
  prises: number;
  total: number;
}

/** Une ligne par catégorie de la séance (ordre de la séance), puis la ligne « Total ». */
export function calculerRemplissage(
  categories: readonly Categorie[],
  places: readonly Place[],
): { lignes: LigneRemplissage[]; total: LigneRemplissage } {
  const parCategorie = new Map<string, LigneRemplissage>(
    categories.map((categorie) => [
      categorie.id,
      { cle: categorie.id, libelle: categorie.nom, prises: 0, total: 0 },
    ]),
  );
  const total: LigneRemplissage = { cle: "total", libelle: "Total", prises: 0, total: 0 };
  for (const place of places) {
    const prise = place.disponible ? 0 : 1;
    total.total += 1;
    total.prises += prise;
    const ligne = parCategorie.get(place.categorie_id);
    if (ligne !== undefined) {
      ligne.total += 1;
      ligne.prises += prise;
    }
  }
  return { lignes: [...parCategorie.values()], total };
}
