// Conversion des erreurs d'API (Problem Details) en une forme affichable ; toute autre erreur
// (HTML, corps vide, panne réseau, rappel OIDC en erreur) donne le message générique.

export const MESSAGE_GENERIQUE =
  "Le service est momentanément indisponible. Réessayez dans quelques instants.";

export interface ErreurChamp {
  champ: string;
  message: string;
}

/** Problem Details converti : `title`, `detail`, `code`, `correlation_id`, `erreurs`. */
export interface ProblemeAffichable {
  titre: string;
  detail: string;
  /** Code métier stable (décision sur `code`, jamais sur le texte) ; `null` hors Problem Details. */
  code: string | null;
  correlationId: string | null;
  erreurs: ErreurChamp[];
}

/** Erreur levée par les fonctions d'API, porteuse du problème converti. */
export class ErreurApi extends Error {
  readonly probleme: ProblemeAffichable;

  constructor(probleme: ProblemeAffichable) {
    super(probleme.titre);
    this.name = "ErreurApi";
    this.probleme = probleme;
  }
}

const EN_TETE_CORRELATION = "X-Correlation-Id";

function problemeGenerique(correlationId: string | null = null): ProblemeAffichable {
  return { titre: MESSAGE_GENERIQUE, detail: "", code: null, correlationId, erreurs: [] };
}

function texteOuNull(valeur: unknown): string | null {
  return typeof valeur === "string" && valeur !== "" ? valeur : null;
}

function erreursDeChamp(valeur: unknown): ErreurChamp[] {
  if (!Array.isArray(valeur)) {
    return [];
  }
  return valeur.flatMap((element: unknown) => {
    if (typeof element !== "object" || element === null) {
      return [];
    }
    const { champ, message } = element as { champ?: unknown; message?: unknown };
    return typeof champ === "string" && typeof message === "string" ? [{ champ, message }] : [];
  });
}

/**
 * Convertit un corps déjà lu (objet JSON, texte ou rien) et sa réponse. Un Problem Details porte
 * `title`, `detail` et `code` ; sinon, message générique.
 */
export function convertirCorps(corps: unknown, reponse: Response): ProblemeAffichable {
  const correlationReponse = texteOuNull(reponse.headers.get(EN_TETE_CORRELATION));
  const typeContenu = reponse.headers.get("Content-Type") ?? "";
  if (!typeContenu.includes("json") || typeof corps !== "object" || corps === null) {
    return problemeGenerique(correlationReponse);
  }
  const { title, detail, code, correlation_id, erreurs } = corps as Record<string, unknown>;
  if (typeof title !== "string" || typeof detail !== "string" || typeof code !== "string") {
    return problemeGenerique(correlationReponse);
  }
  return {
    titre: title,
    detail,
    code,
    correlationId: texteOuNull(correlation_id) ?? correlationReponse,
    erreurs: erreursDeChamp(erreurs),
  };
}

/** Convertit une réponse en erreur ; lit le corps `application/problem+json` s'il y en a un. */
export async function convertirReponse(reponse: Response): Promise<ProblemeAffichable> {
  return convertirCorps(await lireCorps(reponse), reponse);
}

/** Corps JSON de la réponse ; `null` s'il est vide ou illisible (HTML, coupure). */
async function lireCorps(reponse: Response): Promise<unknown> {
  try {
    const texte = await reponse.text();
    return texte === "" ? null : (JSON.parse(texte) as unknown);
  } catch {
    return null;
  }
}

function estProblemeAffichable(valeur: unknown): valeur is ProblemeAffichable {
  if (typeof valeur !== "object" || valeur === null) {
    return false;
  }
  const { titre, detail, erreurs } = valeur as Record<string, unknown>;
  return typeof titre === "string" && typeof detail === "string" && Array.isArray(erreurs);
}

/** Convertit n'importe quelle erreur (ErreurApi, panne réseau, inconnue) en forme affichable. */
export function convertirErreur(erreur: unknown): ProblemeAffichable {
  if (erreur instanceof ErreurApi) {
    return erreur.probleme;
  }
  if (estProblemeAffichable(erreur)) {
    return erreur;
  }
  return problemeGenerique();
}
