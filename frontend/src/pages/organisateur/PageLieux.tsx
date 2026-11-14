// E15 Lieux (route /organisateur/lieux?page=, rôle admin, BIL-022) : lieux paginés et formulaire
// de création (nom, adresse, ville). Un 422 s'affiche sous chaque champ concerné (CA2). Succès :
// notification, formulaire vidé, liste relue.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { creerLieu, listerLieux } from "../../api/catalogue";
import type { Lieu } from "../../api/genere/catalogue";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { ChampFormulaire } from "../../composants/ChampFormulaire";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { TableauPagine, type ColonneTableau } from "../../composants/TableauPagine";
import { Vide } from "../../composants/Vide";
import { useNotifications } from "../../notifications/notifications";
import { lirePage } from "../catalogue/filtres";
import styles from "../catalogue/PageCatalogue.module.css";
import { repartirErreurs } from "./erreursChamps";
import styleOrganisateur from "./Organisateur.module.css";

const CHAMPS = new Set(["nom", "adresse", "ville"]);

const COLONNES_LIEUX: readonly ColonneTableau<Lieu>[] = [
  { entete: "Nom", rendu: (lieu) => lieu.nom },
  { entete: "Adresse", rendu: (lieu) => lieu.adresse },
  { entete: "Ville", rendu: (lieu) => lieu.ville },
];

function FormulaireLieu() {
  const clientRequetes = useQueryClient();
  const { notifier } = useNotifications();
  const [nom, setNom] = useState("");
  const [adresse, setAdresse] = useState("");
  const [ville, setVille] = useState("");

  const creation = useMutation({
    mutationFn: creerLieu,
    onSuccess: (lieu: Lieu) => {
      void clientRequetes.invalidateQueries({ queryKey: ["catalogue", "lieux"] });
      notifier({ type: "succes", message: `Lieu « ${lieu.nom} » créé.` });
      setNom("");
      setAdresse("");
      setVille("");
    },
  });
  const { parChamp, resume } = repartirErreurs(creation.error, CHAMPS);

  const creer = (evenement: FormEvent<HTMLFormElement>) => {
    evenement.preventDefault();
    if (creation.isPending) return;
    creation.mutate({ nom, adresse, ville });
  };

  return (
    // noValidate : la validation est celle de l'API, affichée champ par champ (CA2).
    <form className={styleOrganisateur.formulaire} onSubmit={creer} noValidate>
      <ChampFormulaire
        type="text"
        libelle="Nom"
        nom="nom"
        obligatoire
        valeur={nom}
        surChanger={setNom}
        erreur={parChamp.get("nom")}
      />
      <ChampFormulaire
        type="text"
        libelle="Adresse"
        nom="adresse"
        obligatoire
        autoComplete="street-address"
        valeur={adresse}
        surChanger={setAdresse}
        erreur={parChamp.get("adresse")}
      />
      <ChampFormulaire
        type="text"
        libelle="Ville"
        nom="ville"
        obligatoire
        autoComplete="address-level2"
        valeur={ville}
        surChanger={setVille}
        erreur={parChamp.get("ville")}
      />
      {resume !== null ? <Erreur probleme={resume} /> : null}
      <div>
        <Bouton type="submit" occupe={creation.isPending}>
          Créer le lieu
        </Bouton>
      </div>
    </form>
  );
}

export function PageLieux() {
  const [parametres, setParametres] = useSearchParams();
  const page = lirePage(parametres);
  const idNouveau = useId();

  const lieux = useQuery({
    queryKey: ["catalogue", "lieux", "page", page],
    queryFn: () => listerLieux(page),
    placeholderData: keepPreviousData,
  });

  const changerPage = (numero: number) => {
    const suivants = new URLSearchParams(parametres);
    if (numero > 1) suivants.set("page", String(numero));
    else suivants.delete("page");
    setParametres(suivants);
  };

  return (
    <div className={styles.page}>
      <p className={styles.retour}>
        <Link to="/organisateur">Retour à l'espace organisateur</Link>
      </p>
      <h1>Lieux</h1>
      {lieux.data?.perimee === true ? <BandeauModeDegrade /> : null}
      {lieux.error !== null ? (
        <div className={styles.etat}>
          <Erreur probleme={lieux.error} />
          <Bouton
            variante="secondaire"
            occupe={lieux.isFetching}
            surClic={() => void lieux.refetch()}
          >
            Réessayer
          </Bouton>
        </div>
      ) : lieux.isPending ? (
        <Chargement libelle="Chargement des lieux…" />
      ) : lieux.data.donnees.total === 0 ? (
        <Vide message="Aucun lieu." />
      ) : (
        <TableauPagine
          libelle="Lieux"
          colonnes={COLONNES_LIEUX}
          page={lieux.data.donnees}
          cleLigne={(lieu) => lieu.id}
          surChangerPage={changerPage}
          messageVide="Cette page de lieux est vide."
          occupe={lieux.isFetching && lieux.isPlaceholderData}
        />
      )}
      <section aria-labelledby={idNouveau} className={styles.resultats}>
        <h2 id={idNouveau} className={styles.titreResultats}>
          Nouveau lieu
        </h2>
        <FormulaireLieu />
      </section>
    </div>
  );
}
