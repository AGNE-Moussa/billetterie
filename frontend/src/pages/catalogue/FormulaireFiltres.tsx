// Formulaire des filtres du catalogue (E01) : texte, ville, du, au. Les saisies restent locales
// jusqu'à « Filtrer » (soumission, Entrée comprise), qui les reporte dans l'URL ; « Effacer »
// vide l'URL. L'écran le remonte (`key`) quand l'URL change, pour qu'il reflète toujours ses
// filtres (bouton retour du navigateur, lien partagé).
import { useState, type FormEvent } from "react";

import { Bouton } from "../../composants/Bouton";
import { ChampFormulaire } from "../../composants/ChampFormulaire";
import { FILTRES_VIDES, filtresActifs, type FiltresCatalogue } from "./filtres";
import styles from "./PageCatalogue.module.css";

export interface ProprietesFormulaireFiltres {
  initiaux: FiltresCatalogue;
  surFiltrer: (filtres: FiltresCatalogue) => void;
  surEffacer: () => void;
}

export function FormulaireFiltres({
  initiaux,
  surFiltrer,
  surEffacer,
}: ProprietesFormulaireFiltres) {
  const [filtres, setFiltres] = useState<FiltresCatalogue>(initiaux);

  const modifier = (cle: keyof FiltresCatalogue) => (valeur: string) => {
    setFiltres((courants) => ({ ...courants, [cle]: valeur }));
  };

  const soumettre = (evenement: FormEvent<HTMLFormElement>) => {
    evenement.preventDefault();
    surFiltrer(filtres);
  };

  return (
    <form role="search" aria-label="Filtrer les événements" onSubmit={soumettre}>
      <div className={styles.champs}>
        <ChampFormulaire
          type="search"
          libelle="Rechercher"
          nom="q"
          valeur={filtres.q}
          surChanger={modifier("q")}
          aide="Dans le nom et la description"
        />
        <ChampFormulaire
          type="text"
          libelle="Ville"
          nom="ville"
          valeur={filtres.ville}
          surChanger={modifier("ville")}
          autoComplete="address-level2"
        />
        <ChampFormulaire
          type="date"
          libelle="Du"
          nom="du"
          valeur={filtres.du}
          surChanger={modifier("du")}
          aide="Une séance à partir de ce jour"
        />
        <ChampFormulaire
          type="date"
          libelle="Au"
          nom="au"
          valeur={filtres.au}
          surChanger={modifier("au")}
          aide="Une séance jusqu'à ce jour inclus"
        />
      </div>
      <div className={styles.actionsFiltres}>
        <Bouton type="submit">Filtrer</Bouton>
        <Bouton
          variante="secondaire"
          inactif={!filtresActifs(initiaux) && !filtresActifs(filtres)}
          surClic={() => {
            // Saisies non encore appliquées : l'URL ne change pas, le formulaire est vidé ici.
            setFiltres(FILTRES_VIDES);
            surEffacer();
          }}
        >
          Effacer les filtres
        </Bouton>
      </div>
    </form>
  );
}
