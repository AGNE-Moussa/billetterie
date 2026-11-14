// E01 Catalogue des événements (route /, BIL-019) : filtres et page dans l'URL, liste paginée
// de cartes, états chargement, vide et erreur, bandeau du mode dégradé.
import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useId } from "react";
import { Link, useSearchParams } from "react-router";

import { listerEvenements, type Lecture } from "../../api/catalogue";
import type { EvenementPage } from "../../api/genere/catalogue";
import { convertirErreur } from "../../api/problemes";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { Carte } from "../../composants/Carte";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { Pagination } from "../../composants/Pagination";
import { Vide } from "../../composants/Vide";
import {
  FILTRES_VIDES,
  filtresActifs,
  lireFiltres,
  lirePage,
  versParametres,
  versRequete,
  type FiltresCatalogue,
} from "./filtres";
import { FormulaireFiltres } from "./FormulaireFiltres";
import styles from "./PageCatalogue.module.css";

/** État de navigation transmis à la fiche : son lien « Retour » garde les filtres. */
export interface EtatRetourCatalogue {
  retourCatalogue: string;
}

export function PageCatalogue() {
  const [parametres, setParametres] = useSearchParams();
  const filtres = lireFiltres(parametres);
  const page = lirePage(parametres);
  const recherche = versParametres(filtres, page).toString();
  const idResultats = useId();

  const requete = useQuery({
    queryKey: ["catalogue", "evenements", versRequete(filtres, page)],
    queryFn: () => listerEvenements(versRequete(filtres, page)),
    placeholderData: keepPreviousData,
  });

  const appliquer = (nouveaux: FiltresCatalogue) => {
    // Nouveaux filtres : retour à la première page.
    setParametres(versParametres(nouveaux));
  };
  const effacer = () => setParametres(versParametres(FILTRES_VIDES));
  const changerPage = (numero: number) => setParametres(versParametres(filtres, numero));

  return (
    <div className={styles.page}>
      <h1>Événements</h1>
      <FormulaireFiltres
        key={versParametres(filtres).toString()}
        initiaux={filtres}
        surFiltrer={appliquer}
        surEffacer={effacer}
      />
      <section aria-labelledby={idResultats} className={styles.resultats}>
        <h2 id={idResultats} className={styles.titreResultats}>
          Résultats
        </h2>
        <Resultats
          requete={requete}
          filtresEnCours={filtresActifs(filtres)}
          recherche={recherche}
          surEffacer={effacer}
          surChangerPage={changerPage}
        />
      </section>
    </div>
  );
}

interface ProprietesResultats {
  requete: UseQueryResult<Lecture<EvenementPage>>;
  filtresEnCours: boolean;
  recherche: string;
  surEffacer: () => void;
  surChangerPage: (numero: number) => void;
}

function Resultats({
  requete,
  filtresEnCours,
  recherche,
  surEffacer,
  surChangerPage,
}: ProprietesResultats) {
  const { data, error, isPending, isFetching, isPlaceholderData, refetch } = requete;

  if (error !== null) {
    // 422 (filtres invalides, `du` après `au`) : affiché sous les filtres, à corriger. Autre
    // erreur (503 BASE_INDISPONIBLE, panne) : « Réessayer ».
    const { code } = convertirErreur(error);
    return (
      <div className={styles.etat}>
        <Erreur probleme={error} />
        {code === "REQUETE_INVALIDE" ? null : (
          <Bouton variante="secondaire" occupe={isFetching} surClic={() => void refetch()}>
            Réessayer
          </Bouton>
        )}
      </div>
    );
  }
  if (isPending) {
    return <Chargement libelle="Chargement des événements…" />;
  }

  const { donnees, perimee } = data;
  const { elements, total } = donnees;
  if (elements.length === 0) {
    if (total > 0) {
      return (
        <Vide
          message="Cette page n'existe pas."
          action={
            <Bouton variante="secondaire" surClic={() => surChangerPage(1)}>
              Revenir à la première page
            </Bouton>
          }
        />
      );
    }
    return (
      <>
        {perimee ? <BandeauModeDegrade /> : null}
        {filtresEnCours ? (
          <Vide
            message="Aucun événement ne correspond à ces filtres."
            action={
              <Bouton variante="secondaire" surClic={surEffacer}>
                Effacer les filtres
              </Bouton>
            }
          />
        ) : (
          <Vide message="Aucun événement à l'affiche pour l'instant." />
        )}
      </>
    );
  }

  const etatRetour: EtatRetourCatalogue = {
    retourCatalogue: recherche === "" ? "" : `?${recherche}`,
  };
  const occupe = isFetching && isPlaceholderData;
  return (
    <>
      {perimee ? <BandeauModeDegrade /> : null}
      <p className={styles.nombre}>{total === 1 ? "1 événement" : `${String(total)} événements`}</p>
      <ul className={styles.liste} aria-busy={occupe ? true : undefined}>
        {elements.map((evenement) => (
          <li key={evenement.id}>
            <Carte
              titre={evenement.nom}
              niveauTitre={3}
              actions={
                <Link to={`/evenements/${evenement.id}`} state={etatRetour}>
                  Voir les séances<span className={styles.masque}> de {evenement.nom}</span>
                </Link>
              }
            >
              <p className={styles.description}>{evenement.description}</p>
            </Carte>
          </li>
        ))}
      </ul>
      <Pagination
        page={donnees.page}
        size={donnees.size}
        total={total}
        surChangerPage={surChangerPage}
        occupe={occupe}
      />
    </>
  );
}
