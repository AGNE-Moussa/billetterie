// E04 Paiement de la commande (route /commandes/:commandeId/paiement, rôle customer, BIL-020).
// Compte à rebours jusqu'à `expire_le` renvoyé par l'API (contrainte de BIL-020 : jamais une
// échéance choisie par le front) ; saisie de la carte de test, puis `payerCommande`. Délai
// écoulé : message et retour au plan de salle. Commande qui n'est plus EN_ATTENTE : renvoi vers
// /commandes/:commandeId (E05, BIL-021). Les libellés des places viennent de `listerPlaces`
// (Q6 de docs/front/ecrans.md).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";

import { listerToutesLesPlaces } from "../../api/billets";
import { lireEvenement, lireLieu, lireSeanceParId } from "../../api/catalogue";
import { lireCommande, payerCommande } from "../../api/commandes";
import type { Commande } from "../../api/genere/commandes";
import { convertirErreur } from "../../api/problemes";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { ChampFormulaire } from "../../composants/ChampFormulaire";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { formaterDateHeure, formaterDuree, formaterEuros, formaterHeure } from "../../format";
import { useNotifications } from "../../notifications/notifications";
import { PageIntrouvable } from "../PageIntrouvable";
import styles from "../catalogue/PageCatalogue.module.css";
import { categoriesParId, cleCommande, clePlaces, libellePlace } from "./places";
import styleReservation from "./Reservation.module.css";

/** Un lieu change rarement : relu au plus toutes les cinq minutes. */
const FRAICHEUR_LIEU_MS = 5 * 60 * 1000;

/** Codes qui signifient « cette commande n'existe pas pour vous » (même rendu que 404). */
const CODES_INTROUVABLE = new Set(["ORDER_NOT_FOUND", "REQUETE_INVALIDE"]);

/** Codes après lesquels la commande est expirée, sans débit : plus de paiement possible. */
const CODES_COMMANDE_EXPIREE = new Set([
  "SEAT_ALREADY_TAKEN",
  "SHOW_CANCELLED",
  "SHOW_ALREADY_STARTED",
]);

/** Codes après lesquels la commande est relue (état changé par une autre requête). */
const CODES_RELIRE = new Set(["REQUEST_IN_PROGRESS", "ORDER_NOT_PENDING"]);

const MOTIF_CARTE = /^[0-9]{16}$/;

/** Millisecondes restantes avant `expireLe` (date de l'API), relues chaque seconde. */
function useTempsRestant(expireLe: string | undefined): number | null {
  const [maintenant, setMaintenant] = useState(() => Date.now());
  useEffect(() => {
    if (expireLe === undefined) return undefined;
    const minuterie = window.setInterval(() => setMaintenant(Date.now()), 1000);
    return () => window.clearInterval(minuterie);
  }, [expireLe]);
  if (expireLe === undefined) return null;
  return Date.parse(expireLe) - maintenant;
}

function codeDe(erreur: unknown): string | null {
  return erreur === null ? null : convertirErreur(erreur).code;
}

function LienPlan({ seanceId }: { seanceId: string }) {
  return <Link to={`/seances/${seanceId}`}>Retour au plan de salle</Link>;
}

export function PagePaiement() {
  const { commandeId = "" } = useParams();
  const naviguer = useNavigate();
  const clientRequetes = useQueryClient();
  const { notifier } = useNotifications();
  const [carte, setCarte] = useState("");
  const [erreurCarte, setErreurCarte] = useState<string | undefined>(undefined);

  const commande = useQuery({
    queryKey: cleCommande(commandeId),
    queryFn: () => lireCommande(commandeId),
  });
  const seanceId = commande.data?.seance_id;
  const seance = useQuery({
    queryKey: ["catalogue", "seance", seanceId ?? ""],
    queryFn: () => lireSeanceParId(seanceId ?? ""),
    enabled: seanceId !== undefined,
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
    queryKey: clePlaces(seanceId ?? ""),
    queryFn: () => listerToutesLesPlaces(seanceId ?? ""),
    enabled: seanceId !== undefined,
  });
  const restant = useTempsRestant(commande.data?.expire_le);

  const paiement = useMutation({
    mutationFn: (carteTest: string) => payerCommande(commandeId, carteTest),
    onSuccess: (payee: Commande) => {
      clientRequetes.setQueryData(cleCommande(commandeId), payee);
      notifier({ type: "succes", message: "Paiement accepté : votre commande est confirmée." });
      void naviguer(`/commandes/${commandeId}`, { replace: true });
    },
    onError: (erreur) => {
      const code = codeDe(erreur);
      if (code !== null && CODES_RELIRE.has(code)) {
        void commande.refetch();
      }
      if (
        seanceId !== undefined &&
        (code === "PAYMENT_REFUSED" || CODES_COMMANDE_EXPIREE.has(code ?? ""))
      ) {
        // Places libérées : le plan de la séance est relu à la prochaine visite.
        void clientRequetes.invalidateQueries({ queryKey: clePlaces(seanceId) });
      }
    },
  });

  if (CODES_INTROUVABLE.has(codeDe(commande.error) ?? "")) {
    return <PageIntrouvable />;
  }
  if (commande.error !== null) {
    return (
      <div className={styles.page}>
        <h1>Paiement</h1>
        <div className={styles.etat}>
          <Erreur probleme={commande.error} />
          <Bouton
            variante="secondaire"
            occupe={commande.isFetching}
            surClic={() => void commande.refetch()}
          >
            Réessayer
          </Bouton>
        </div>
      </div>
    );
  }
  if (commande.isPending) {
    return (
      <div className={styles.page}>
        <h1>Paiement</h1>
        <Chargement libelle="Chargement de la commande…" />
      </div>
    );
  }

  const donnees = commande.data;
  const codePaiement = codeDe(paiement.error);
  const paiementTermine =
    codePaiement === "PAYMENT_REFUSED" || CODES_COMMANDE_EXPIREE.has(codePaiement ?? "");
  if (donnees.statut !== "EN_ATTENTE" && !paiementTermine && !paiement.isSuccess) {
    return <Navigate to={`/commandes/${commandeId}`} replace />;
  }

  const expiree = restant !== null && restant <= 0;
  const categories = categoriesParId(seance.data?.donnees.categories ?? []);
  const placesParId = new Map((places.data ?? []).map((place) => [place.id, place]));
  const perimee =
    seance.data?.perimee === true ||
    evenement.data?.perimee === true ||
    lieu.data?.perimee === true;

  const payer = (evenementFormulaire: FormEvent<HTMLFormElement>) => {
    evenementFormulaire.preventDefault();
    const numero = carte.replace(/\s/g, "");
    if (!MOTIF_CARTE.test(numero)) {
      setErreurCarte("Saisissez les 16 chiffres du numéro de carte de test.");
      return;
    }
    setErreurCarte(undefined);
    paiement.mutate(numero);
  };

  let issue;
  if (codePaiement === "PAYMENT_REFUSED") {
    issue = (
      <div role="alert" className={styleReservation.alerte}>
        <p>
          <strong>Paiement refusé, vos places sont libérées.</strong>
        </p>
        <p>
          <LienPlan seanceId={donnees.seance_id} />
        </p>
      </div>
    );
  } else if (paiementTermine) {
    issue = (
      <div className={styleReservation.alerte}>
        <Erreur probleme={paiement.error} />
        <p>Votre commande a expiré ; aucun paiement n'a été débité.</p>
        <p>
          <LienPlan seanceId={donnees.seance_id} />
        </p>
      </div>
    );
  } else if (expiree) {
    issue = (
      <div role="alert" className={styleReservation.alerte}>
        <p>
          <strong>Le délai de réservation est écoulé.</strong>
        </p>
        <p>Vos places sont libérées et aucun paiement n'a été effectué.</p>
        <p>
          <LienPlan seanceId={donnees.seance_id} />
        </p>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <h1>Paiement</h1>
      {perimee ? <BandeauModeDegrade /> : null}
      <p className={styleReservation.sousTitre}>
        {evenement.data?.donnees.nom ?? "Séance"}
        {seance.data !== undefined ? (
          <>
            {" - "}
            <time dateTime={seance.data.donnees.debut}>
              {formaterDateHeure(seance.data.donnees.debut)}
            </time>
          </>
        ) : null}
        {lieu.data !== undefined ? ` - ${lieu.data.donnees.nom}, ${lieu.data.donnees.ville}` : null}
      </p>

      {issue === undefined && restant !== null ? (
        <p className={styleReservation.compteARebours}>
          Places réservées pour vous encore{" "}
          <strong role="timer" aria-label={`Temps restant : ${formaterDuree(restant)}`}>
            {formaterDuree(restant)}
          </strong>{" "}
          (jusqu'à {formaterHeure(donnees.expire_le)})
        </p>
      ) : null}

      <table className={styleReservation.lignes}>
        <caption className={styles.masque}>Places de la commande</caption>
        <thead>
          <tr>
            <th scope="col">Place</th>
            <th scope="col" className={styleReservation.montant}>
              Montant
            </th>
          </tr>
        </thead>
        <tbody>
          {donnees.lignes.map((ligne) => {
            const place = placesParId.get(ligne.place_id);
            const categorie =
              place !== undefined ? categories.get(place.categorie_id)?.nom : undefined;
            return (
              <tr key={ligne.place_id}>
                <td>
                  {place !== undefined ? libellePlace(place) : "Place"}
                  {categorie !== undefined ? ` (${categorie})` : null}
                </td>
                <td className={styleReservation.montant}>{formaterEuros(ligne.montant)}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Total</th>
            <td className={styleReservation.montant}>{formaterEuros(donnees.montant_total)}</td>
          </tr>
        </tfoot>
      </table>

      {issue ?? (
        <form className={styleReservation.formulaire} onSubmit={payer} noValidate>
          <ChampFormulaire
            type="text"
            libelle="Numéro de carte de test"
            nom="carte_test"
            autoComplete="off"
            obligatoire
            valeur={carte}
            surChanger={setCarte}
            erreur={erreurCarte}
            aide="Paiement simulé, aucune carte réelle : 4000000000000002 est refusé, tout autre numéro de 16 chiffres est accepté (par exemple 4242424242424242)."
          />
          {paiement.error !== null ? (
            <div className={styleReservation.alerte}>
              {codePaiement !== null && codePaiement.endsWith("_INDISPONIBLE") ? (
                <p>
                  Paiement momentanément impossible. Réessayez avant{" "}
                  {formaterHeure(donnees.expire_le)}.
                </p>
              ) : null}
              <Erreur probleme={paiement.error} />
            </div>
          ) : null}
          <div className={styleReservation.actions}>
            <Bouton type="submit" occupe={paiement.isPending}>
              Payer {formaterEuros(donnees.montant_total)}
            </Bouton>
            <Link to={`/seances/${donnees.seance_id}`}>Abandonner</Link>
          </div>
        </form>
      )}
    </div>
  );
}
