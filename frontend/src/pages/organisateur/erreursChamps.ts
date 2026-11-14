// Erreurs de validation de l'API réparties sous les champs du formulaire (CA2 de BIL-022).
// Le Problem Details 422 porte `erreurs: [{champ, message}]`, où `champ` est le chemin Pydantic
// joint par des points (« body.nom », « body.categories.0.prix ») : le préfixe « body. » est
// retiré pour obtenir le nom du champ du formulaire. Les erreurs sans champ affiché restent dans
// le résumé (composant Erreur), pour qu'aucune ne soit perdue.
import { convertirErreur, type ProblemeAffichable } from "../../api/problemes";

const PREFIXE_CORPS = "body.";

export interface ErreursReparties {
  /** Message d'erreur par nom de champ du formulaire. */
  parChamp: ReadonlyMap<string, string>;
  /** Problème à afficher en résumé (sans les erreurs déjà placées), `null` sans erreur. */
  resume: ProblemeAffichable | null;
}

export const AUCUNE_ERREUR: ErreursReparties = { parChamp: new Map(), resume: null };

function nomDuChamp(champ: string): string {
  return champ.startsWith(PREFIXE_CORPS) ? champ.slice(PREFIXE_CORPS.length) : champ;
}

/**
 * Répartit l'erreur d'une soumission. `champsAffiches` : les noms des champs présents à l'écran.
 * `champsParCode` : code métier sans tableau `erreurs` rattaché à un champ (par exemple
 * `SHOW_START_IN_PAST` sous la date) ; son `detail` s'affiche sous le champ.
 */
export function repartirErreurs(
  erreur: unknown,
  champsAffiches: ReadonlySet<string>,
  champsParCode: Readonly<Record<string, string>> = {},
): ErreursReparties {
  if (erreur === null || erreur === undefined) {
    return AUCUNE_ERREUR;
  }
  const probleme = convertirErreur(erreur);
  const parChamp = new Map<string, string>();
  const restantes = probleme.erreurs.filter(({ champ, message }) => {
    const nom = nomDuChamp(champ);
    if (!champsAffiches.has(nom)) {
      return true;
    }
    const precedent = parChamp.get(nom);
    parChamp.set(nom, precedent === undefined ? message : `${precedent} ${message}`);
    return false;
  });

  const champDuCode = probleme.code !== null ? champsParCode[probleme.code] : undefined;
  if (champDuCode !== undefined && champsAffiches.has(champDuCode) && probleme.detail !== "") {
    parChamp.set(champDuCode, probleme.detail);
    // Le détail est déjà sous le champ : le résumé garde le titre seul.
    return { parChamp, resume: { ...probleme, detail: "", erreurs: restantes } };
  }
  return { parChamp, resume: { ...probleme, erreurs: restantes } };
}
