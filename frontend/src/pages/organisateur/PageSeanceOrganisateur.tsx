// E14 Séance : remplissage et annulation (route /organisateur/seances/:seanceId, rôle admin,
// BIL-022). Places prises sur total, par catégorie, calculées sur `listerPlaces` (Q4 : aucune
// route d'agrégat ; prises = verrouillées ou vendues). « Annuler la séance » passe par une
// confirmation explicite ; 409 SHOW_ALREADY_CANCELLED ou SHOW_ALREADY_STARTED : message et
// séance relue. Succès : notification, bouton retiré.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useParams } from "react-router";

import { listerToutesLesPlaces } from "../../api/billets";
import {
  annulerSeance,
  lireEvenement,
  lireLieu,
  lireSeanceParId,
  type Lecture,
} from "../../api/catalogue";
import type { Seance } from "../../api/genere/catalogue";
import { convertirErreur } from "../../api/problemes";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { Chargement } from "../../composants/Chargement";
import { DialogueConfirmation } from "../../composants/DialogueConfirmation";
import { Erreur } from "../../composants/Erreur";
import { Vide } from "../../composants/Vide";
import { formaterDateHeure, formaterEuros } from "../../format";
import { useNotifications } from "../../notifications/notifications";
import { PageIntrouvable } from "../PageIntrouvable";
import styles from "../catalogue/PageCatalogue.module.css";
import { clePlaces } from "../reservation/places";
import styleReservation from "../reservation/Reservation.module.css";
import styleOrganisateur from "./Organisateur.module.css";
import { calculerRemplissage } from "./remplissage";

/** Un lieu change rarement : relu au plus toutes les cinq minutes. */
const FRAICHEUR_LIEU_MS = 5 * 60 * 1000;

const CODES_INTROUVABLE = new Set(["SHOW_NOT_FOUND", "REQUETE_INVALIDE"]);

/** Refus d'annulation qui viennent de l'état de la séance : elle est relue. */
const CODES_SEANCE_A_RELIRE = new Set(["SHOW_ALREADY_CANCELLED", "SHOW_ALREADY_STARTED"]);

function codeDe(erreur: unknown): string | null {
  return erreur === null ? null : convertirErreur(erreur).code;
}

export function PageSeanceOrganisateur() {
  const { seanceId = "" } = useParams();
  const clientRequetes = useQueryClient();
  const { notifier } = useNotifications();
  const [confirmation, setConfirmation] = useState(false);
  const idRemplissage = useId();
  const cleSeance = ["catalogue", "seance", seanceId] as const;

  const seance = useQuery({
    queryKey: cleSeance,
    queryFn: () => lireSeanceParId(seanceId),
  });
  const evenementId = seance.data?.donnees.evenement_id;
  const lieuId = seance.data?.donnees.lieu_id;
  const evenement = useQuery({
    queryKey: ["catalogue", "evenement", evenementId ?? ""],
    queryFn: () => lireEvenement(evenementId ?? ""),
    enabled: evenementId !== undefined,
  });
  const lieu = useQuery({
    queryKey: ["catalogue", "lieu", lieuId ?? ""],
    queryFn: () => lireLieu(lieuId ?? ""),
    enabled: lieuId !== undefined,
    staleTime: FRAICHEUR_LIEU_MS,
  });
  const places = useQuery({
    queryKey: clePlaces(seanceId),
    queryFn: () => listerToutesLesPlaces(seanceId),
  });

  const annulation = useMutation({
    mutationFn: () => annulerSeance(evenementId ?? "", seanceId),
    onSettled: () => setConfirmation(false),
    onSuccess: (annulee: Seance) => {
      clientRequetes.setQueryData<Lecture<Seance>>(cleSeance, {
        donnees: annulee,
        perimee: false,
      });
      void clientRequetes.invalidateQueries({
        queryKey: ["catalogue", "seances", annulee.evenement_id],
      });
      notifier({ type: "succes", message: "Séance annulée, remboursements en cours." });
    },
    onError: (erreur) => {
      if (CODES_SEANCE_A_RELIRE.has(codeDe(erreur) ?? "")) {
        void seance.refetch();
      }
    },
  });

  if (CODES_INTROUVABLE.has(codeDe(seance.error) ?? "")) {
    return <PageIntrouvable />;
  }
  if (seance.error !== null) {
    return (
      <div className={styles.page}>
        <h1>Séance</h1>
        <div className={styles.etat}>
          <Erreur probleme={seance.error} />
          <Bouton
            variante="secondaire"
            occupe={seance.isFetching}
            surClic={() => void seance.refetch()}
          >
            Réessayer
          </Bouton>
        </div>
      </div>
    );
  }
  if (seance.isPending) {
    return (
      <div className={styles.page}>
        <h1>Séance</h1>
        <Chargement libelle="Chargement de la séance…" />
      </div>
    );
  }

  const donnees = seance.data.donnees;
  const dateSeance = formaterDateHeure(donnees.debut);
  const perimee =
    seance.data.perimee || evenement.data?.perimee === true || lieu.data?.perimee === true;

  const confirmer = () => {
    if (annulation.isPending) return;
    annulation.mutate();
  };

  let remplissage;
  if (places.error !== null) {
    remplissage = (
      <div className={styles.etat}>
        <Erreur probleme={places.error} />
        <Bouton
          variante="secondaire"
          occupe={places.isFetching}
          surClic={() => void places.refetch()}
        >
          Réessayer
        </Bouton>
      </div>
    );
  } else if (places.isPending) {
    remplissage = <Chargement libelle="Calcul du remplissage…" />;
  } else if (places.data.length === 0) {
    remplissage = (
      <Vide
        message="Places en cours de création."
        action={
          <Bouton
            variante="secondaire"
            occupe={places.isFetching}
            surClic={() => void places.refetch()}
          >
            Rafraîchir
          </Bouton>
        }
      />
    );
  } else {
    const { lignes, total } = calculerRemplissage(donnees.categories, places.data);
    remplissage = (
      <>
        <table className={styleReservation.lignes} aria-busy={places.isFetching ? true : undefined}>
          <caption className={styles.masque}>Remplissage par catégorie</caption>
          <thead>
            <tr>
              <th scope="col">Catégorie</th>
              <th scope="col" className={styleReservation.montant}>
                Places prises
              </th>
              <th scope="col" className={styleReservation.montant}>
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {lignes.map((ligne) => (
              <tr key={ligne.cle}>
                <th scope="row">{ligne.libelle}</th>
                <td className={styleReservation.montant}>{ligne.prises}</td>
                <td className={styleReservation.montant}>{ligne.total}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">{total.libelle}</th>
              <td className={styleReservation.montant}>{total.prises}</td>
              <td className={styleReservation.montant}>{total.total}</td>
            </tr>
          </tfoot>
        </table>
        <p className={styleOrganisateur.note}>
          Places prises : verrouillées pour une commande en cours ou vendues.
        </p>
        <div>
          <Bouton
            variante="secondaire"
            occupe={places.isFetching}
            surClic={() => void places.refetch()}
          >
            Rafraîchir
          </Bouton>
        </div>
      </>
    );
  }

  return (
    <div className={styles.page}>
      <p className={styles.retour}>
        <Link to={`/organisateur/evenements/${donnees.evenement_id}`}>
          Retour à {evenement.data?.donnees.nom ?? "l'événement"}
        </Link>
      </p>
      {perimee ? <BandeauModeDegrade /> : null}
      <h1>Séance du {dateSeance}</h1>
      <p className={styleReservation.sousTitre}>
        {evenement.data?.donnees.nom ?? "Événement"}
        {lieu.data !== undefined ? ` - ${lieu.data.donnees.nom}, ${lieu.data.donnees.ville}` : null}
      </p>
      {donnees.annulee ? (
        <p>
          <strong className={styles.annulee}>Séance annulée.</strong> Les acheteurs sont remboursés.
        </p>
      ) : null}
      <ul className={styleOrganisateur.liste}>
        {donnees.categories.map((categorie) => (
          <li key={categorie.id}>
            {categorie.nom} : {formaterEuros(categorie.prix)}, rangs{" "}
            {categorie.rangs.map((rang) => rang.rang).join(", ")}
          </li>
        ))}
      </ul>

      <section aria-labelledby={idRemplissage} className={styles.resultats}>
        <h2 id={idRemplissage} className={styles.titreResultats}>
          Remplissage
        </h2>
        {remplissage}
      </section>

      {annulation.error !== null ? (
        <div className={styleReservation.alerte}>
          <Erreur probleme={annulation.error} />
        </div>
      ) : null}
      {!donnees.annulee ? (
        <div className={styleOrganisateur.actions}>
          <Bouton
            variante="danger"
            occupe={annulation.isPending}
            inactif={evenementId === undefined}
            surClic={() => setConfirmation(true)}
          >
            Annuler la séance
          </Bouton>
        </div>
      ) : null}
      <DialogueConfirmation
        ouvert={confirmation}
        titre={`Annuler la séance du ${dateSeance} ?`}
        message="Tous les acheteurs seront remboursés et prévenus, et leurs billets annulés."
        libelleAnnuler="Garder la séance"
        libelleConfirmer="Confirmer l'annulation"
        occupe={annulation.isPending}
        surConfirmer={confirmer}
        surAnnuler={() => {
          if (!annulation.isPending) setConfirmation(false);
        }}
      />
    </div>
  );
}
