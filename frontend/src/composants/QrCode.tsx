// QR code dessiné côté client en SVG (E08, BIL-021) à partir d'une valeur opaque (le `qr_code`
// du billet : identifiant signé, aucune donnée lisible). Matrice calculée par qrcode-generator,
// rendue en un seul <path> ; aucun HTML injecté. Toujours sombre sur clair, quel que soit le
// thème, avec la marge blanche de quatre modules exigée par la norme pour la lecture.
import qrcode from "qrcode-generator";
import { useMemo } from "react";

/** Marge blanche autour du code, en modules (zone de silence de la norme). */
const MARGE_MODULES = 4;

export interface ProprietesQrCode {
  valeur: string;
  /** Nom accessible de l'image. */
  libelle: string;
  /** Côté affiché, en pixels CSS. */
  taille?: number;
}

/** Chemin SVG des modules sombres, un carré d'un module par case. */
function cheminModules(valeur: string): { chemin: string; cote: number } {
  // Type 0 : version choisie selon la longueur ; correction M (15 %).
  const code = qrcode(0, "M");
  code.addData(valeur);
  code.make();
  const modules = code.getModuleCount();
  const morceaux: string[] = [];
  for (let ligne = 0; ligne < modules; ligne += 1) {
    for (let colonne = 0; colonne < modules; colonne += 1) {
      if (code.isDark(ligne, colonne)) {
        morceaux.push(
          `M${String(colonne + MARGE_MODULES)} ${String(ligne + MARGE_MODULES)}h1v1h-1z`,
        );
      }
    }
  }
  return { chemin: morceaux.join(""), cote: modules + 2 * MARGE_MODULES };
}

export function QrCode({ valeur, libelle, taille = 240 }: ProprietesQrCode) {
  const { chemin, cote } = useMemo(() => cheminModules(valeur), [valeur]);
  return (
    <svg
      role="img"
      aria-label={libelle}
      width={taille}
      height={taille}
      viewBox={`0 0 ${String(cote)} ${String(cote)}`}
      shapeRendering="crispEdges"
    >
      <rect width={cote} height={cote} fill="#ffffff" />
      <path d={chemin} fill="#000000" />
    </svg>
  );
}
