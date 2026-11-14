// E10 Espace organisateur : événements (route /organisateur?q=&page=, rôle admin, BIL-022).
// Événements paginés avec recherche, dans l'URL ; actions « Créer un événement » et « Lieux ».
// La garde `admin` est posée par la route parente (RoutesApplication) : un client, un revendeur
// ou un visiteur n'atteint jamais cet écran (CA1).
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { listerEvenements, type FiltresEvenements } from "../../api/catalogue";
import type { Evenement } from "../../api/genere/catalogue";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { ChampFormulaire } from "../../composants/ChampFormulaire";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { TableauPagine, type ColonneTableau } from "../../composants/TableauPagine";
import { Vide } from "../../composants/Vide";
import { formaterDateHeure } from "../../format";
import { lirePage } from "../catalogue/filtres";
import styles from "../catalogue/PageCatalogue.module.css";
import styleOrganisateur from "./Organisateur.module.css";

/** Formulaire de recherche, réinitialisé quand `q` change dans l'URL (clé React). */
function Recherche({
  initiale,
  surChercher,
}: {
  initiale: string;
  surChercher: (q: string) => void;
}) {
  const [saisie, setSaisie] = useState(initiale);
  const chercher = (evenement: FormEvent<HTMLFormElement>) => {
    evenement.preventDefault();
    surChercher(saisie.trim());
  };
  return (
    <form role="search" className={styleOrganisateur.recherche} onSubmit={chercher}>
      <ChampFormulaire
        type="search"
        libelle="Rechercher un événement"
        nom="q"
        valeur={saisie}
        surChanger={setSaisie}
      />
      <Bouton type="submit" variante="secondaire">
        Rechercher
      </Bouton>
    </form>
  );
}

export function PageOrganisateur() {
  const [parametres, setParametres] = useSearchParams();
  const q = parametres.get("q")?.trim() ?? "";
  const page = lirePage(parametres);
  const requete: FiltresEvenements = q !== "" ? { q, page } : { page };

  const evenements = useQuery({
    queryKey: ["catalogue", "evenements", requete],
    queryFn: () => listerEvenements(requete),
    placeholderData: keepPreviousData,
  });

  const versParametres = (recherche: string, numero: number) => {
    const suivants = new URLSearchParams();
    if (recherche !== "") suivants.set("q", recherche);
    if (numero > 1) suivants.set("page", String(numero));
    return suivants;
  };

  return (
    <div className={styles.page}>
      <h1>Espace organisateur</h1>
      <div className={styleOrganisateur.actions}>
        <Link to="/organisateur/evenements/nouveau">Créer un événement</Link>
        <Link to="/organisateur/lieux">Lieux</Link>
      </div>
      <Recherche
        key={q}
        initiale={q}
        surChercher={(recherche) => setParametres(versParametres(recherche, 1))}
      />
      {evenements.data?.perimee === true ? <BandeauModeDegrade /> : null}
      {evenements.error !== null ? (
        <div className={styles.etat}>
          <Erreur probleme={evenements.error} />
          <Bouton
            variante="secondaire"
            occupe={evenements.isFetching}
            surClic={() => void evenements.refetch()}
          >
            Réessayer
          </Bouton>
        </div>
      ) : evenements.isPending ? (
        <Chargement libelle="Chargement des événements…" />
      ) : evenements.data.donnees.total === 0 ? (
        <Vide
          message={
            q !== "" ? "Aucun événement ne correspond à cette recherche." : "Aucun événement."
          }
          action={<Link to="/organisateur/evenements/nouveau">Créer un événement</Link>}
        />
      ) : (
        <TableauPagine
          libelle="Événements"
          colonnes={COLONNES_EVENEMENTS}
          page={evenements.data.donnees}
          cleLigne={(evenement) => evenement.id}
          surChangerPage={(numero) => setParametres(versParametres(q, numero))}
          messageVide="Cette page d'événements est vide."
          occupe={evenements.isFetching && evenements.isPlaceholderData}
        />
      )}
    </div>
  );
}

const COLONNES_EVENEMENTS: readonly ColonneTableau<Evenement>[] = [
  { entete: "Événement", rendu: (evenement) => evenement.nom },
  {
    entete: "Créé le",
    rendu: (evenement) => (
      <time dateTime={evenement.cree_le}>{formaterDateHeure(evenement.cree_le)}</time>
    ),
  },
  {
    entete: "Action",
    rendu: (evenement) => (
      <Link to={`/organisateur/evenements/${evenement.id}`}>
        Gérer<span className={styles.masque}> l'événement {evenement.nom}</span>
      </Link>
    ),
  },
];
