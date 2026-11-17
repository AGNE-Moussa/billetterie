// File d'attente d'une séance (US8, BIL-023), partagée par E03 (plan de salle) et E16 (salle
// d'attente).
//
// Le jeton d'admission n'est gardé que dans le cache TanStack Query, en mémoire de l'onglet :
// jamais dans localStorage ni sessionStorage. CA1 (rafraîchir ne fait pas perdre sa place) est
// tenu par le serveur : `entrerFile` est idempotent et rend la position, ou le même jeton
// d'admission tant qu'il n'a pas expiré ; après un rafraîchissement, le front le redemande.
import type { PositionFile } from "../../api/fileAttente";

/** Clé de cache de la position (ou de l'admission) de l'appelant dans la file d'une séance. */
export function cleFile(seanceId: string): readonly string[] {
  return ["file-attente", seanceId];
}

/** `entrerFile` 404 : la séance n'est pas sous file, le plan de salle s'ouvre directement. */
export const CODE_SANS_FILE = "QUEUE_NOT_FOUND";

/** `lirePositionFile` 404 : l'appelant n'est plus dans la file (admission expirée). */
export const CODE_HORS_FILE = "QUEUE_POSITION_NOT_FOUND";

/** `creerCommande` 403 : jeton d'admission absent ou refusé, retour en salle d'attente. */
export const CODES_ADMISSION = new Set(["ADMISSION_REQUIRED", "ADMISSION_INVALID"]);

/** Motif d'un renvoi de E03 vers E16, porté par l'état de navigation. */
export type MotifRetourAttente = "admission-refusee" | "admission-expiree";

export interface EtatRetourAttente {
  motif: MotifRetourAttente;
}

/** Lit le motif d'un renvoi vers E16 dans l'état de navigation (`location.state`). */
export function motifRetour(etat: unknown): MotifRetourAttente | null {
  if (typeof etat !== "object" || etat === null) return null;
  const { motif } = etat as { motif?: unknown };
  return motif === "admission-refusee" || motif === "admission-expiree" ? motif : null;
}

/** Chemin de E16 ; `recherche` garde la sélection du plan (`?places=`). */
export function cheminAttente(seanceId: string, recherche = ""): string {
  return `/seances/${seanceId}/attente${recherche}`;
}

/** Chemin de E03 ; `recherche` garde la sélection du plan (`?places=`). */
export function cheminPlan(seanceId: string, recherche = ""): string {
  return `/seances/${seanceId}${recherche}`;
}

/** Intervalle minimal entre deux lectures de la position (contrainte de BIL-023). */
export const INTERVALLE_MIN_MS = 5_000;
/** Intervalle maximal : une longue attente estimée n'espace pas les lectures au-delà. */
export const INTERVALLE_MAX_MS = 30_000;

/**
 * Délai avant la prochaine lecture de la position : le quart de l'attente estimée, borné entre
 * 5 et 30 secondes. Une attente longue est relue moins souvent, jamais plus d'une fois toutes
 * les 5 secondes.
 */
export function intervalleInterrogation(position: PositionFile | undefined): number {
  const estimee = position?.attente_estimee_secondes;
  if (estimee === null || estimee === undefined) return INTERVALLE_MIN_MS;
  return Math.min(INTERVALLE_MAX_MS, Math.max(INTERVALLE_MIN_MS, (estimee * 1000) / 4));
}

/** Attente estimée lisible (« moins d'une minute », « environ 6 min »). */
export function formaterAttente(secondes: number | null): string {
  if (secondes === null) return "inconnue";
  if (secondes < 60) return "moins d'une minute";
  return `environ ${String(Math.round(secondes / 60))} min`;
}
