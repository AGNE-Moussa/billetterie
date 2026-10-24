// Dialogue de confirmation contrôlé, sur <dialog> natif ouvert par showModal() : nommé par son
// titre, décrit par son message, focus initial sur « Annuler », Échap annule, clic hors du
// dialogue sans effet, focus rendu au déclencheur à la fermeture. Une fermeture par le
// navigateur (hors de la prop `ouvert`) appelle `surAnnuler`.
import { useEffect, useId, useRef, type SyntheticEvent } from "react";

import { Bouton } from "./Bouton";
import styles from "./DialogueConfirmation.module.css";

export interface ProprietesDialogueConfirmation {
  ouvert: boolean;
  titre: string;
  message: string;
  surConfirmer: () => void;
  /**
   * Doit passer `ouvert` à false (composant contrôlé). Le dialogue n'est pas rouvert si `ouvert`
   * reste vrai après une fermeture par le navigateur.
   */
  surAnnuler: () => void;
  /** « Confirmer » par défaut. */
  libelleConfirmer?: string;
  /** « Annuler » par défaut. */
  libelleAnnuler?: string;
}

export function DialogueConfirmation({
  ouvert,
  titre,
  message,
  surConfirmer,
  surAnnuler,
  libelleConfirmer = "Confirmer",
  libelleAnnuler = "Annuler",
}: ProprietesDialogueConfirmation) {
  const dialogue = useRef<HTMLDialogElement>(null);
  const idTitre = useId();
  const idMessage = useId();

  // Vrai entre un close() demandé par le composant et l'événement `close` qui le suit (émis
  // plus tard par le navigateur) : cette fermeture-là n'est pas une annulation.
  const fermetureDemandee = useRef(false);

  useEffect(() => {
    const element = dialogue.current;
    if (element === null) {
      return;
    }
    if (ouvert && !element.open) {
      // showModal rend le reste de la page inerte et retient l'élément focalisé, auquel le
      // navigateur rend le focus à la fermeture. « Annuler » est le premier bouton.
      element.showModal();
      element.querySelector("button")?.focus();
    } else if (!ouvert && element.open) {
      fermetureDemandee.current = true;
      element.close();
    }
  }, [ouvert]);

  useEffect(() => {
    const element = dialogue.current;
    return () => {
      // Démontage pendant l'ouverture : fermer lève la modalité et rend le focus.
      if (element?.open === true) {
        fermetureDemandee.current = true;
        element.close();
      }
    };
  }, []);

  const surEchap = (evenement: SyntheticEvent<HTMLDialogElement>) => {
    if (!evenement.cancelable) {
      // Échap répété sans activation (Chromium) : le navigateur fermera le dialogue quoi qu'il
      // arrive, et `surFermeture` signalera l'annulation une seule fois.
      return;
    }
    // Dialogue contrôlé : Échap ne le ferme pas lui-même, l'écran passe `ouvert` à false.
    evenement.preventDefault();
    surAnnuler();
  };

  const surFermeture = () => {
    if (fermetureDemandee.current) {
      fermetureDemandee.current = false;
      return;
    }
    // Fermé par le navigateur alors que `ouvert` est vrai : l'écran réaligne son état.
    surAnnuler();
  };

  return (
    <dialog
      ref={dialogue}
      className={styles.dialogue}
      aria-labelledby={idTitre}
      aria-describedby={idMessage}
      onCancel={surEchap}
      onClose={surFermeture}
    >
      <h2 id={idTitre} className={styles.titre}>
        {titre}
      </h2>
      <p id={idMessage} className={styles.message}>
        {message}
      </p>
      <div className={styles.actions}>
        <Bouton variante="secondaire" surClic={surAnnuler}>
          {libelleAnnuler}
        </Bouton>
        <Bouton variante="danger" surClic={surConfirmer}>
          {libelleConfirmer}
        </Bouton>
      </div>
    </dialog>
  );
}
