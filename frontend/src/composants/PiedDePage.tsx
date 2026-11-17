// Pied de page (contentinfo) : la marque, des rubriques d'information et le copyright.
// Volontairement sans lien : aucune page légale ni d'aide n'existe, et l'ordre de
// tabulation de la mise en page s'arrête au contenu (BIL-F28).
import { Logo } from "./Logo";
import styles from "./PiedDePage.module.css";

const RUBRIQUES = [
  {
    titre: "Billetterie",
    elements: ["Concerts, théâtre, humour", "Places numérotées", "Billets avec QR code"],
  },
  {
    titre: "Vos achats",
    elements: [
      "Places garanties : jamais vendues deux fois",
      "Places gardées le temps du paiement",
      "Paiement en ligne en quelques secondes",
    ],
  },
  {
    titre: "Organisateurs",
    elements: ["Lieux et plans de salle", "Séances et catégories", "Salle d'attente virtuelle"],
  },
] as const;

export function PiedDePage() {
  return (
    <footer className={styles.pied}>
      <div className={styles.interieur}>
        <div className={styles.marque}>
          <Logo />
          <p className={styles.accroche}>
            Billetterie de spectacles : choisissez votre place, on s'occupe du reste.
          </p>
        </div>
        {RUBRIQUES.map((rubrique) => (
          <div key={rubrique.titre} className={styles.rubrique}>
            <p className={styles.titre}>{rubrique.titre}</p>
            <ul className={styles.liste}>
              {rubrique.elements.map((element) => (
                <li key={element}>{element}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className={styles.mentions}>
        <p>© {new Date().getFullYear()} Ovation. Tous droits réservés.</p>
      </div>
    </footer>
  );
}
