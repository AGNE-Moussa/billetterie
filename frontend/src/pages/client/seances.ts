// Séances, événements et lieux d'une liste de commandes ou de billets (E05 à E08) : un appel par
// identifiant distinct, mis en cache par TanStack Query sous les mêmes clés que E02 à E04. Une
// séance illisible n'empêche pas l'affichage du reste (« Séance indisponible », ecrans.md E06).
import { useQueries } from "@tanstack/react-query";

import { lireEvenement, lireLieu, lireSeanceParId } from "../../api/catalogue";
import type { Evenement, Lieu, Seance } from "../../api/genere/catalogue";
import { formaterDateHeure } from "../../format";

/** Un lieu change rarement : relu au plus toutes les cinq minutes. */
const FRAICHEUR_LIEU_MS = 5 * 60 * 1000;

export interface InfosSeance {
  seance?: Seance;
  evenement?: Evenement;
  lieu?: Lieu;
  /** Vrai si la séance, son événement ou son lieu n'a pas pu être lu. */
  enErreur: boolean;
  /** Vrai si une lecture vient du cache de secours (`X-Cache-Stale`). */
  perimee: boolean;
}

function distincts(valeurs: readonly (string | undefined)[]): string[] {
  return [...new Set(valeurs.filter((valeur): valeur is string => valeur !== undefined))];
}

/** Séance, événement et lieu de chaque identifiant de séance, lus en parallèle. */
export function useInfosSeances(seanceIds: readonly string[]): Map<string, InfosSeance> {
  const ids = distincts(seanceIds);
  const seances = useQueries({
    queries: ids.map((seanceId) => ({
      queryKey: ["catalogue", "seance", seanceId],
      queryFn: () => lireSeanceParId(seanceId),
    })),
  });
  const idsEvenements = distincts(seances.map((lecture) => lecture.data?.donnees.evenement_id));
  const idsLieux = distincts(seances.map((lecture) => lecture.data?.donnees.lieu_id));
  const evenements = useQueries({
    queries: idsEvenements.map((evenementId) => ({
      queryKey: ["catalogue", "evenement", evenementId],
      queryFn: () => lireEvenement(evenementId),
    })),
  });
  const lieux = useQueries({
    queries: idsLieux.map((lieuId) => ({
      queryKey: ["catalogue", "lieu", lieuId],
      queryFn: () => lireLieu(lieuId),
      staleTime: FRAICHEUR_LIEU_MS,
    })),
  });

  const evenementsParId = new Map(
    idsEvenements.map((id, index) => [id, evenements[index]] as const),
  );
  const lieuxParId = new Map(idsLieux.map((id, index) => [id, lieux[index]] as const));

  const resultat = new Map<string, InfosSeance>();
  ids.forEach((seanceId, index) => {
    const lectureSeance = seances[index];
    const seance = lectureSeance?.data?.donnees;
    const lectureEvenement =
      seance !== undefined ? evenementsParId.get(seance.evenement_id) : undefined;
    const lectureLieu = seance !== undefined ? lieuxParId.get(seance.lieu_id) : undefined;
    resultat.set(seanceId, {
      seance,
      evenement: lectureEvenement?.data?.donnees,
      lieu: lectureLieu?.data?.donnees,
      enErreur:
        (lectureSeance?.error ?? null) !== null ||
        (lectureEvenement?.error ?? null) !== null ||
        (lectureLieu?.error ?? null) !== null,
      perimee:
        lectureSeance?.data?.perimee === true ||
        lectureEvenement?.data?.perimee === true ||
        lectureLieu?.data?.perimee === true,
    });
  });
  return resultat;
}

/** « Nom de l'événement, sam. 12/12/2026 20:00, Salle X (Lyon) » ou un état de chargement. */
export function descriptionSeance(infos: InfosSeance | undefined): string {
  if (infos?.seance === undefined) {
    return infos?.enErreur === true ? "Séance indisponible" : "Chargement de la séance…";
  }
  const morceaux = [
    infos.evenement?.nom ?? (infos.enErreur ? "Événement indisponible" : "Événement"),
    formaterDateHeure(infos.seance.debut),
  ];
  if (infos.lieu !== undefined) {
    morceaux.push(`${infos.lieu.nom} (${infos.lieu.ville})`);
  }
  return morceaux.join(", ");
}
