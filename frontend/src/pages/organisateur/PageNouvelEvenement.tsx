// E11 Nouvel événement (route /organisateur/evenements/nouveau, rôle admin, BIL-022). Les règles
// de validation sont celles de l'API : un 422 REQUETE_INVALIDE s'affiche sous chaque champ
// concerné (CA2) ; 403 et 503 en résumé. Succès : notification et renvoi vers E12.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { creerEvenement } from "../../api/catalogue";
import type { Evenement } from "../../api/genere/catalogue";
import { Bouton } from "../../composants/Bouton";
import { ChampFormulaire } from "../../composants/ChampFormulaire";
import { Erreur } from "../../composants/Erreur";
import { useNotifications } from "../../notifications/notifications";
import styles from "../catalogue/PageCatalogue.module.css";
import { repartirErreurs } from "./erreursChamps";
import styleOrganisateur from "./Organisateur.module.css";

const CHAMPS = new Set(["nom", "description"]);

export function PageNouvelEvenement() {
  const naviguer = useNavigate();
  const clientRequetes = useQueryClient();
  const { notifier } = useNotifications();
  const [nom, setNom] = useState("");
  const [description, setDescription] = useState("");

  const creation = useMutation({
    mutationFn: creerEvenement,
    onSuccess: (evenement: Evenement) => {
      void clientRequetes.invalidateQueries({ queryKey: ["catalogue", "evenements"] });
      notifier({ type: "succes", message: `Événement « ${evenement.nom} » créé.` });
      void naviguer(`/organisateur/evenements/${evenement.id}`);
    },
  });
  const { parChamp, resume } = repartirErreurs(creation.error, CHAMPS);

  const creer = (evenement: FormEvent<HTMLFormElement>) => {
    evenement.preventDefault();
    if (creation.isPending) return;
    creation.mutate({ nom, description });
  };

  return (
    <div className={styles.page}>
      <p className={styles.retour}>
        <Link to="/organisateur">Retour à l'espace organisateur</Link>
      </p>
      <h1>Nouvel événement</h1>
      {/* noValidate : la validation est celle de l'API, affichée champ par champ (CA2). */}
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
          type="textarea"
          libelle="Description"
          nom="description"
          valeur={description}
          surChanger={setDescription}
          erreur={parChamp.get("description")}
        />
        {resume !== null ? <Erreur probleme={resume} /> : null}
        <div className={styleOrganisateur.actions}>
          <Bouton type="submit" occupe={creation.isPending}>
            Créer
          </Bouton>
          <Link to="/organisateur">Annuler</Link>
        </div>
      </form>
    </div>
  );
}
