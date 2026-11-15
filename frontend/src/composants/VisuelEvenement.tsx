// Visuel d'événement généré (affiche ou bannière), sans aucune image externe : un dégradé et un
// motif SVG choisis de façon déterministe à partir d'une graine (l'identifiant de l'événement),
// et l'initiale du nom en filigrane. Le même événement a donc toujours le même visuel. Purement
// décoratif : masqué des technologies d'assistance (le nom est lu dans le titre de la page).
import { useId, useMemo, type ReactNode } from "react";

import styles from "./VisuelEvenement.module.css";

/** Paires de couleurs du dégradé : toutes assez sombres pour un texte blanc par-dessus. */
const PALETTES: readonly (readonly [string, string, string])[] = [
  ["#b0127a", "#5b2ee0", "#ff7ac8"],
  ["#7a1fa2", "#1f2a8a", "#c49bff"],
  ["#c2410c", "#8a1550", "#ffb37a"],
  ["#0f5f73", "#3b1d8f", "#6fe3e0"],
  ["#8a1538", "#2d0f4f", "#ff8aa8"],
  ["#4a2bb0", "#0e5a63", "#9ad8ff"],
  ["#a3125f", "#c2410c", "#ffd27a"],
  ["#1e3a8a", "#701a75", "#f0abfc"],
];

const PALETTE_DEFAUT = ["#b0127a", "#5b2ee0", "#ff7ac8"] as const;

const MOTIFS = 6;

/** Hachage FNV-1a 32 bits : stable, rapide, assez dispersé pour choisir couleurs et motif. */
function hacher(texte: string): number {
  let empreinte = 0x811c9dc5;
  for (let indice = 0; indice < texte.length; indice += 1) {
    empreinte ^= texte.charCodeAt(indice);
    empreinte = Math.imul(empreinte, 0x01000193);
  }
  return empreinte >>> 0;
}

/** Suite pseudo-aléatoire déterministe (mulberry32) tirée de la graine. */
function generateur(graine: number): () => number {
  let etat = graine;
  return () => {
    etat = (etat + 0x6d2b79f5) >>> 0;
    let t = etat;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function motif(numero: number, hasard: () => number, largeur: number, hauteur: number): ReactNode {
  const clair = "rgba(255, 255, 255, 0.16)";
  const tresClair = "rgba(255, 255, 255, 0.08)";
  switch (numero) {
    case 0: {
      // Anneaux concentriques, comme un projecteur sur la scène.
      const cx = largeur * (0.55 + hasard() * 0.35);
      const cy = hauteur * (0.2 + hasard() * 0.6);
      return Array.from({ length: 9 }, (_, i) => (
        <circle
          key={i}
          cx={cx}
          cy={cy}
          r={28 + i * 34}
          fill="none"
          stroke={i % 2 === 0 ? clair : tresClair}
          strokeWidth={i % 3 === 0 ? 10 : 3}
        />
      ));
    }
    case 1: {
      // Faisceaux de lumière partant du haut.
      const origine = largeur * (0.2 + hasard() * 0.6);
      return Array.from({ length: 7 }, (_, i) => {
        const ecart = (i - 3) * (largeur / 7);
        return (
          <path
            key={i}
            d={`M${String(origine)} -10 L${String(origine + ecart - 40)} ${String(hauteur + 10)} L${String(origine + ecart + 40)} ${String(hauteur + 10)} Z`}
            fill={i % 2 === 0 ? clair : tresClair}
          />
        );
      });
    }
    case 2: {
      // Ondes horizontales (musique).
      const amplitude = 14 + hasard() * 18;
      return Array.from({ length: 8 }, (_, i) => {
        const y = (hauteur / 8) * i + 12;
        const pas = largeur / 4;
        return (
          <path
            key={i}
            d={`M-20 ${String(y)} q ${String(pas / 2)} ${String(-amplitude)} ${String(pas)} 0 t ${String(pas)} 0 t ${String(pas)} 0 t ${String(pas)} 0 t ${String(pas)} 0`}
            fill="none"
            stroke={i % 2 === 0 ? clair : tresClair}
            strokeWidth={i % 3 === 0 ? 6 : 2.5}
          />
        );
      });
    }
    case 3: {
      // Trame de points (rangs de sièges).
      const points: ReactNode[] = [];
      const pas = 26;
      for (let y = pas / 2; y < hauteur; y += pas) {
        for (let x = pas / 2; x < largeur; x += pas) {
          const r = 2 + ((x * 7 + y * 3) % 5);
          points.push(
            <circle key={`${String(x)}-${String(y)}`} cx={x} cy={y} r={r} fill={tresClair} />,
          );
        }
      }
      return points;
    }
    case 4: {
      // Bandes diagonales (rideau).
      return Array.from({ length: 14 }, (_, i) => (
        <rect
          key={i}
          x={i * 60 - hauteur}
          y={-20}
          width={i % 3 === 0 ? 30 : 12}
          height={hauteur * 2}
          fill={i % 2 === 0 ? clair : tresClair}
          transform={`skewX(${String(-30 + Math.round(hasard() * 10))})`}
        />
      ));
    }
    default: {
      // Confettis et étoiles (fête, humour).
      return Array.from({ length: 34 }, (_, i) => {
        const x = hasard() * largeur;
        const y = hasard() * hauteur;
        const taille = 3 + hasard() * 9;
        return i % 3 === 0 ? (
          <path
            key={i}
            d={`M${String(x)} ${String(y - taille)} L${String(x + taille * 0.3)} ${String(y - taille * 0.3)} L${String(x + taille)} ${String(y)} L${String(x + taille * 0.3)} ${String(y + taille * 0.3)} L${String(x)} ${String(y + taille)} L${String(x - taille * 0.3)} ${String(y + taille * 0.3)} L${String(x - taille)} ${String(y)} L${String(x - taille * 0.3)} ${String(y - taille * 0.3)} Z`}
            fill={clair}
          />
        ) : (
          <rect
            key={i}
            x={x}
            y={y}
            width={taille}
            height={taille * 0.45}
            rx={1}
            fill={i % 2 === 0 ? clair : tresClair}
            transform={`rotate(${String(Math.round(hasard() * 180))} ${String(x)} ${String(y)})`}
          />
        );
      });
    }
  }
}

export interface ProprietesVisuelEvenement {
  /** Graine du visuel : l'identifiant de l'événement. */
  graine: string;
  /** Nom de l'événement : son initiale apparaît en filigrane. */
  nom: string;
  /** `affiche` (carte, 5:3) ou `banniere` (fiche, très large). */
  format?: "affiche" | "banniere";
  /** Éléments posés sur le visuel (pastille de date, badge). */
  children?: ReactNode;
}

export function VisuelEvenement({
  graine,
  nom,
  format = "affiche",
  children,
}: ProprietesVisuelEvenement) {
  const idDegrade = useId();
  const idLueur = useId();
  const largeur = format === "affiche" ? 400 : 1200;
  const hauteur = format === "affiche" ? 240 : 360;

  const { palette, dessin, angle } = useMemo(() => {
    const empreinte = hacher(graine);
    const hasard = generateur(empreinte);
    return {
      palette: PALETTES[empreinte % PALETTES.length] ?? PALETTE_DEFAUT,
      dessin: motif((empreinte >>> 8) % MOTIFS, hasard, largeur, hauteur),
      angle: Math.round(hasard() * 90),
    };
  }, [graine, largeur, hauteur]);
  const initiale = nom.trim().charAt(0).toUpperCase() || "O";

  return (
    <div className={`${styles.visuel ?? ""} ${styles[format] ?? ""}`}>
      <svg
        viewBox={`0 0 ${String(largeur)} ${String(hauteur)}`}
        preserveAspectRatio="xMidYMid slice"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <linearGradient
            id={idDegrade}
            gradientTransform={`rotate(${String(angle)} 0.5 0.5)`}
            x1="0"
            y1="0"
            x2="1"
            y2="1"
          >
            <stop offset="0" stopColor={palette[0]} />
            <stop offset="1" stopColor={palette[1]} />
          </linearGradient>
          <radialGradient id={idLueur} cx="0.8" cy="0.1" r="0.8">
            <stop offset="0" stopColor={palette[2]} stopOpacity="0.55" />
            <stop offset="1" stopColor={palette[2]} stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect width={largeur} height={hauteur} fill={`url(#${idDegrade})`} />
        <rect width={largeur} height={hauteur} fill={`url(#${idLueur})`} />
        <g>{dessin}</g>
        <text
          x={largeur - (format === "affiche" ? 24 : 80)}
          y={hauteur - (format === "affiche" ? 18 : 30)}
          textAnchor="end"
          className={styles.initiale}
          fontSize={format === "affiche" ? 190 : 320}
        >
          {initiale}
        </text>
      </svg>
      {children !== undefined ? <div className={styles.surcouche}>{children}</div> : null}
    </div>
  );
}
