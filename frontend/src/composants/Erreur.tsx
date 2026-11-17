// Affiche une erreur d'API en alerte (role="alert") : titre, détail, erreurs de champ et
// « Référence : <correlationId> » ; message générique pour toute erreur non convertible. L'icône
// est décorative et sans texte : l'alerte n'annonce que le message.
import { convertirErreur } from "../api/problemes";
import styles from "./Erreur.module.css";

export interface ProprietesErreur {
  /** Problème converti (`ProblemeAffichable`) ou erreur brute (`ErreurApi`, panne, inconnue). */
  probleme: unknown;
}

export function Erreur({ probleme }: ProprietesErreur) {
  const { titre, detail, erreurs, correlationId } = convertirErreur(probleme);
  return (
    <div role="alert" className={styles.erreur}>
      <svg
        className={styles.icone}
        viewBox="0 0 24 24"
        width="22"
        height="22"
        aria-hidden="true"
        focusable="false"
      >
        <circle cx="12" cy="12" r="10" fill="currentColor" />
        <path d="M12 7v6" stroke="#ffffff" strokeWidth="2.4" strokeLinecap="round" />
        <circle cx="12" cy="16.8" r="1.4" fill="#ffffff" />
      </svg>
      <div className={styles.texte}>
        <p>
          <strong>{titre}</strong>
        </p>
        {detail !== "" ? <p>{detail}</p> : null}
        {erreurs.length > 0 ? (
          <ul>
            {erreurs.map(({ champ, message }, index) => (
              // L'index rend la clé unique même si le serveur répète une erreur de champ ; la
              // liste est figée (jamais réordonnée), l'index y est donc stable.
              <li key={`${String(index)} ${champ} ${message}`}>
                {champ} : {message}
              </li>
            ))}
          </ul>
        ) : null}
        {correlationId !== null ? (
          <p className={styles.reference}>Référence : {correlationId}</p>
        ) : null}
      </div>
    </div>
  );
}
