// Affiche une erreur d'API en alerte (role="alert") : titre, détail, erreurs de champ et
// « Référence : <correlationId> » ; message générique pour toute erreur non convertible.
import { convertirErreur } from "../api/problemes";

export interface ProprietesErreur {
  /** Problème converti (`ProblemeAffichable`) ou erreur brute (`ErreurApi`, panne, inconnue). */
  probleme: unknown;
}

export function Erreur({ probleme }: ProprietesErreur) {
  const { titre, detail, erreurs, correlationId } = convertirErreur(probleme);
  return (
    <div role="alert">
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
      {correlationId !== null ? <p>Référence : {correlationId}</p> : null}
    </div>
  );
}
