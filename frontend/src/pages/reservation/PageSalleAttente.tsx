// E16 Salle d'attente (route /seances/:seanceId/attente, rôle customer, BIL-023). Entre dans la
// file de la séance (`entrerFile`, idempotent : un rafraîchissement retrouve sa place, CA1),
// puis relit la position (`lirePositionFile`) toutes les 5 à 30 secondes selon l'attente
// estimée, jamais plus souvent. À l'admission, la position (jeton d'admission compris) est
// déposée dans le cache en mémoire et le client est renvoyé vers le plan de salle (E03).
// Séance sans file (404 QUEUE_NOT_FOUND) : plan de salle direct.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation, useNavigate, useParams } from "react-router";

import { lireEvenement, lireSeanceParId } from "../../api/catalogue";
import { entrerFile, lirePositionFile, type PositionFile } from "../../api/fileAttente";
import { convertirErreur } from "../../api/problemes";
import { Bouton } from "../../composants/Bouton";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { formaterDateHeure, formaterHeure } from "../../format";
import styles from "../catalogue/PageCatalogue.module.css";
import {
  CODE_HORS_FILE,
  CODE_SANS_FILE,
  cleFile,
  cheminPlan,
  formaterAttente,
  intervalleInterrogation,
  type MotifRetourAttente,
  motifRetour,
} from "./fileAttente";
import styleReservation from "./Reservation.module.css";

const FORMAT_ENTIER = new Intl.NumberFormat("fr-FR");

function codeDe(erreur: unknown): string | null {
  return erreur === null ? null : convertirErreur(erreur).code;
}

const MESSAGES_RETOUR: Record<MotifRetourAttente, string> = {
  "admission-refusee":
    "Votre admission n'a pas été acceptée pour la réservation : elle a expiré ou n'est plus valable.",
  "admission-expiree": "Votre délai d'achat est écoulé.",
};

function MessageRetour({ motif }: { motif: MotifRetourAttente }) {
  return (
    <div role="alert" className={styleReservation.alerte}>
      <p>
        <strong>{MESSAGES_RETOUR[motif]}</strong>
      </p>
      <p>Vous êtes de nouveau dans la file d'attente de cette séance.</p>
    </div>
  );
}

export function PageSalleAttente() {
  const { seanceId = "" } = useParams();
  const { search, state } = useLocation();
  const naviguer = useNavigate();
  const clientRequetes = useQueryClient();
  const motif = motifRetour(state);
  // Première requête de la page : `entrerFile` (place retrouvée ou prise) ; ensuite
  // `lirePositionFile`. Remis à faux quand l'appelant n'est plus dans la file.
  const entre = useRef(false);
  const [positionDepart, setPositionDepart] = useState<number | null>(null);

  const seance = useQuery({
    queryKey: ["catalogue", "seance", seanceId],
    queryFn: () => lireSeanceParId(seanceId),
  });
  const evenementId = seance.data?.donnees.evenement_id;
  const evenement = useQuery({
    queryKey: ["catalogue", "evenement", evenementId ?? ""],
    queryFn: () => lireEvenement(evenementId ?? ""),
    enabled: evenementId !== undefined,
  });

  const file = useQuery({
    queryKey: [...cleFile(seanceId), "attente"],
    queryFn: async (): Promise<PositionFile> => {
      if (!entre.current) {
        const position = await entrerFile(seanceId);
        entre.current = true;
        return position;
      }
      try {
        return await lirePositionFile(seanceId);
      } catch (erreur) {
        // Admission expirée ou place perdue : « Reprendre une place » rentrera dans la file.
        if (codeDe(erreur) === CODE_HORS_FILE) entre.current = false;
        throw erreur;
      }
    },
    // Jamais de position d'une visite précédente : chaque ouverture repart de `entrerFile`.
    gcTime: 0,
    refetchInterval: (requete) =>
      requete.state.error === null && requete.state.data?.statut === "EN_ATTENTE"
        ? intervalleInterrogation(requete.state.data)
        : false,
  });

  const codeErreur = codeDe(file.error);

  const position = file.data;
  const rang = position?.statut === "EN_ATTENTE" ? position.position : null;
  if (rang !== null && (positionDepart === null || rang > positionDepart)) {
    setPositionDepart(rang);
  }

  // Après un renvoi depuis E03, l'admission n'est pas suivie d'elle-même (pas de va-et-vient
  // si le serveur la tient encore pour valable) : le client choisit d'y retourner.
  const redirigerALAdmission = position?.statut === "ADMIS" && motif === null;
  useEffect(() => {
    if (position?.statut !== "ADMIS") return;
    clientRequetes.setQueryData(cleFile(seanceId), position);
    if (motif === null) {
      void naviguer(cheminPlan(seanceId, search), { replace: true });
    }
  }, [position, motif, seanceId, search, clientRequetes, naviguer]);

  if (codeErreur === CODE_SANS_FILE) {
    return <Navigate to={cheminPlan(seanceId, search)} replace />;
  }

  const donneesSeance = seance.data?.donnees;
  const entete = (
    <div className={styleReservation.entete}>
      <h1>{evenement.data?.donnees.nom ?? "Salle d'attente"}</h1>
      {donneesSeance !== undefined ? (
        <p className={styleReservation.sousTitre}>
          <time dateTime={donneesSeance.debut}>{formaterDateHeure(donneesSeance.debut)}</time>
        </p>
      ) : null}
    </div>
  );

  let contenu;
  if (codeErreur === CODE_HORS_FILE) {
    contenu = (
      <div className={styles.etat}>
        <div role="alert" className={styleReservation.alerte}>
          <p>
            <strong>Vous n'êtes plus dans la file d'attente.</strong>
          </p>
          <p>Votre admission a expiré. Vous pouvez reprendre une place en fin de file.</p>
        </div>
        <Bouton occupe={file.isFetching} surClic={() => void file.refetch()}>
          Reprendre une place dans la file
        </Bouton>
      </div>
    );
  } else if (file.error !== null) {
    contenu = (
      <div className={styles.etat}>
        <Erreur probleme={file.error} />
        <Bouton variante="secondaire" occupe={file.isFetching} surClic={() => void file.refetch()}>
          Réessayer
        </Bouton>
      </div>
    );
  } else if (position === undefined) {
    contenu = <Chargement libelle="Connexion à la file d'attente…" />;
  } else if (position.statut === "ADMIS") {
    contenu = redirigerALAdmission ? (
      <Chargement libelle="C'est votre tour : ouverture du plan de salle…" />
    ) : (
      <div className={styles.etat}>
        <p role="status" aria-live="polite">
          <strong>C'est votre tour.</strong>{" "}
          {position.admission_expire_le !== null
            ? `Vous pouvez réserver jusqu'à ${formaterHeure(position.admission_expire_le)}.`
            : null}
        </p>
        <p>
          <Link to={cheminPlan(seanceId, search)} replace>
            Aller au plan de salle
          </Link>
        </p>
      </div>
    );
  } else {
    contenu = (
      <section className={styles.resultats} aria-labelledby="titre-file">
        <h2 id="titre-file" className={styles.titreResultats}>
          Vous êtes dans la file d'attente
        </h2>
        <p role="status" aria-live="polite">
          Position : {rang === null ? "inconnue" : FORMAT_ENTIER.format(rang)} - Attente estimée :{" "}
          {formaterAttente(position.attente_estimee_secondes)}
        </p>
        {rang !== null && positionDepart !== null ? (
          <progress
            aria-label="Progression dans la file d'attente"
            max={positionDepart}
            value={positionDepart - rang + 1}
          />
        ) : null}
        <p>
          Gardez cette page ouverte : vous serez redirigé vers le plan de salle à votre tour.
          Rafraîchir la page ne vous fait pas perdre votre place.
        </p>
      </section>
    );
  }

  return (
    <div className={styles.page}>
      <p className={styles.retour}>
        {evenementId !== undefined ? (
          <Link to={`/evenements/${evenementId}`}>Retour à l'événement</Link>
        ) : (
          <Link to="/">Retour au catalogue</Link>
        )}
      </p>
      {entete}
      {motif !== null ? <MessageRetour motif={motif} /> : null}
      {contenu}
    </div>
  );
}
