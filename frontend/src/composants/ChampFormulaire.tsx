// Champ de formulaire contrôlé : libellé visible associé (id par useId), mention
// « (obligatoire) », aide et erreur liées par aria-describedby, aria-invalid en erreur.
import { useId, type ChangeEvent } from "react";

import styles from "./ChampFormulaire.module.css";

export interface OptionChamp {
  valeur: string;
  libelle: string;
}

interface ProprietesCommunesChamp {
  libelle: string;
  valeur: string;
  surChanger: (valeur: string) => void;
  /** Message d'erreur affiché sous le champ ; absent : champ valide. */
  erreur?: string;
  aide?: string;
  obligatoire?: boolean;
  nom?: string;
  autoComplete?: string;
}

export type ProprietesChampFormulaire = ProprietesCommunesChamp &
  (
    | { type: "text" | "email" | "number" | "password" | "textarea" }
    | { type: "select"; options: readonly OptionChamp[] }
  );

export function ChampFormulaire(proprietes: ProprietesChampFormulaire) {
  const { libelle, valeur, surChanger, erreur, aide, obligatoire = false, nom } = proprietes;
  const id = useId();
  const idAide = `${id}-aide`;
  const idErreur = `${id}-erreur`;
  const enErreur = erreur !== undefined && erreur !== "";
  const avecAide = aide !== undefined && aide !== "";
  const descriptions = [avecAide ? idAide : null, enErreur ? idErreur : null].filter(
    (identifiant): identifiant is string => identifiant !== null,
  );

  const attributs = {
    id,
    name: nom,
    value: valeur,
    required: obligatoire,
    autoComplete: proprietes.autoComplete,
    "aria-invalid": enErreur ? true : undefined,
    "aria-describedby": descriptions.length > 0 ? descriptions.join(" ") : undefined,
    className: `${styles.saisie ?? ""} ${enErreur ? (styles.saisieEnErreur ?? "") : ""}`,
    onChange: (
      evenement: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
    ) => surChanger(evenement.target.value),
  };

  let saisie;
  if (proprietes.type === "select") {
    saisie = (
      <select {...attributs}>
        {proprietes.options.map((option) => (
          <option key={option.valeur} value={option.valeur}>
            {option.libelle}
          </option>
        ))}
      </select>
    );
  } else if (proprietes.type === "textarea") {
    saisie = <textarea {...attributs} rows={4} />;
  } else {
    saisie = <input {...attributs} type={proprietes.type} />;
  }

  return (
    <div className={styles.champ}>
      <label htmlFor={id} className={styles.libelle}>
        {libelle}
        {obligatoire ? <span className={styles.obligatoire}> (obligatoire)</span> : null}
      </label>
      {saisie}
      {avecAide ? (
        <p id={idAide} className={styles.aide}>
          {aide}
        </p>
      ) : null}
      {enErreur ? (
        <p id={idErreur} className={styles.erreur}>
          {erreur}
        </p>
      ) : null}
    </div>
  );
}
