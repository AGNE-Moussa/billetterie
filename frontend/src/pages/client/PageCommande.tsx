// E05 Suivi d'une commande (route /commandes/:commandeId, rôle customer, BIL-021) ; sert de page
// de confirmation après le paiement (E04). Statut, séance, lignes et total ; selon le statut :
// CONFIRMEE, billets de la commande (`listerBillets?commande_id=`), relus toutes les quelques
// secondes tant qu'ils ne sont pas tous émis (émission asynchrone), avec un nombre de relectures
// borné ; EN_ATTENTE, compte à rebours et lien vers le paiement ; EXPIREE et REMBOURSEE,
// message clair. Commande d'un autre client : même rendu qu'une page introuvable.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { listerBillets, listerToutesLesPlaces } from "../../api/billets";
import { lireCommande } from "../../api/commandes";
import type { Billet } from "../../api/genere/billets";
import type { Commande } from "../../api/genere/commandes";
import { convertirErreur } from "../../api/problemes";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { formaterDateHeure, formaterDuree, formaterEuros, formaterHeure } from "../../format";
import { PageIntrouvable } from "../PageIntrouvable";
import styles from "../catalogue/PageCatalogue.module.css";
import { categoriesParId, cleCommande, clePlaces, libellePlace } from "../reservation/places";
import styleReservation from "../reservation/Reservation.module.css";
import { useTempsRestant } from "../reservation/tempsRestant";
import { cleBilletsCommande, LIBELLES_STATUT_BILLET, LIBELLES_STATUT_COMMANDE } from "./libelles";
import { descriptionSeance, useInfosSeances } from "./seances";

/** Codes qui signifient « cette commande n'existe pas pour vous » (même rendu que 404). */
const CODES_INTROUVABLE = new Set(["ORDER_NOT_FOUND", "REQUETE_INVALIDE"]);

/** Intervalle des relectures des billets pendant leur émission. */
const INTERVALLE_BILLETS_MS = 3000;

/** Relectures au plus (environ une minute) ; au-delà, message « ils arriveront par e-mail ». */
const RELECTURES_BILLETS_MAX = 20;

/** Une commande compte 10 places au plus : une page de billets suffit. */
const TAILLE_PAGE_BILLETS = 100;

function codeDe(erreur: unknown): string | null {
  return erreur === null ? null : convertirErreur(erreur).code;
}

/** Message principal selon le statut (ecrans.md E05). */
function MessageStatut({ commande }: { commande: Commande }) {
  const restant = useTempsRestant(
    commande.statut === "EN_ATTENTE" ? commande.expire_le : undefined,
  );
  const lienSeance = <Link to={`/seances/${commande.seance_id}`}>Retour à la séance</Link>;
  switch (commande.statut) {
    case "CONFIRMEE":
      return (
        <div role="status" className={styleReservation.recapitulatif}>
          <p>
            <strong>Paiement accepté.</strong> Vos billets arrivent aussi par e-mail.
          </p>
        </div>
      );
    case "EN_ATTENTE":
      if (restant !== null && restant <= 0) {
        return (
          <div role="alert" className={styleReservation.alerte}>
            <p>
              <strong>Le délai de réservation est écoulé.</strong>
            </p>
            <p>Vos places sont libérées et aucun paiement n'a été effectué.</p>
            <p>{lienSeance}</p>
          </div>
        );
      }
      return (
        <div className={styleReservation.recapitulatif}>
          {restant !== null ? (
            <p className={styleReservation.compteARebours}>
              Places réservées pour vous encore{" "}
              <strong role="timer" aria-label={`Temps restant : ${formaterDuree(restant)}`}>
                {formaterDuree(restant)}
              </strong>{" "}
              (jusqu'à {formaterHeure(commande.expire_le)})
            </p>
          ) : null}
          <Link to={`/commandes/${commande.id}/paiement`}>
            Payer {formaterEuros(commande.montant_total)}
          </Link>
        </div>
      );
    case "EXPIREE":
      return (
        <div role="alert" className={styleReservation.alerte}>
          <p>
            <strong>Commande expirée : aucun débit, vos places sont libérées.</strong>
          </p>
          <p>{lienSeance}</p>
        </div>
      );
    case "REMBOURSEE":
      return (
        <div role="alert" className={styleReservation.alerte}>
          <p>
            <strong>Séance annulée, commande remboursée.</strong>
          </p>
          <p>Vos billets de cette commande sont annulés.</p>
        </div>
      );
  }
}

export function PageCommande() {
  const { commandeId = "" } = useParams();
  const clientRequetes = useQueryClient();

  const commande = useQuery({
    queryKey: cleCommande(commandeId),
    queryFn: () => lireCommande(commandeId),
  });
  const donnees = commande.data;
  const seanceId = donnees?.seance_id;
  const infos = useInfosSeances(seanceId !== undefined ? [seanceId] : []).get(seanceId ?? "");
  const places = useQuery({
    queryKey: clePlaces(seanceId ?? ""),
    queryFn: () => listerToutesLesPlaces(seanceId ?? ""),
    enabled: seanceId !== undefined,
  });
  const nombreLignes = donnees?.lignes.length ?? 0;
  const avecBillets = donnees?.statut === "CONFIRMEE" || donnees?.statut === "REMBOURSEE";
  const billets = useQuery({
    queryKey: cleBilletsCommande(commandeId),
    queryFn: () => listerBillets(1, { commandeId, size: TAILLE_PAGE_BILLETS }),
    enabled: avecBillets,
    // Émission asynchrone (ticketing.order.confirmed) : relue tant qu'il manque des billets,
    // au plus RELECTURES_BILLETS_MAX fois ; une commande remboursée n'est pas relue.
    refetchInterval: (requete) => {
      if (donnees?.statut !== "CONFIRMEE") return false;
      const emis = requete.state.data?.elements.length ?? 0;
      if (emis >= nombreLignes) return false;
      if (requete.state.dataUpdateCount >= RELECTURES_BILLETS_MAX) return false;
      return INTERVALLE_BILLETS_MS;
    },
  });
  // Lectures déjà faites (l'état de la requête, relu à chaque nouvelle donnée).
  const lecturesBillets =
    clientRequetes.getQueryState(cleBilletsCommande(commandeId))?.dataUpdateCount ?? 0;

  if (CODES_INTROUVABLE.has(codeDe(commande.error) ?? "")) {
    return <PageIntrouvable />;
  }
  if (commande.error !== null) {
    return (
      <div className={styles.page}>
        <h1>Commande</h1>
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
  if (donnees === undefined) {
    return (
      <div className={styles.page}>
        <h1>Commande</h1>
        <Chargement libelle="Chargement de la commande…" />
      </div>
    );
  }

  const categories = categoriesParId(infos?.seance?.categories ?? []);
  const placesParId = new Map((places.data ?? []).map((place) => [place.id, place]));
  const billetsParPlace = new Map<string, Billet>(
    (billets.data?.elements ?? []).map((billet) => [billet.place_id, billet]),
  );
  // Billets encore attendus et relectures non épuisées : « Émission en cours ».
  const emissionEnCours =
    donnees.statut === "CONFIRMEE" &&
    billetsParPlace.size < nombreLignes &&
    billets.error === null &&
    lecturesBillets < RELECTURES_BILLETS_MAX;

  return (
    <div className={styles.page}>
      <div className={styleReservation.entete}>
        <h1>Commande du {formaterDateHeure(donnees.cree_le)}</h1>
        <p className={styleReservation.sousTitre}>
          Statut : <strong>{LIBELLES_STATUT_COMMANDE[donnees.statut]}</strong>
        </p>
        <p className={styleReservation.sousTitre}>{descriptionSeance(infos)}</p>
      </div>
      {infos?.perimee === true ? <BandeauModeDegrade /> : null}

      <MessageStatut commande={donnees} />

      <table className={styleReservation.lignes}>
        <caption className={styles.masque}>Places de la commande</caption>
        <thead>
          <tr>
            <th scope="col">Place</th>
            <th scope="col" className={styleReservation.montant}>
              Montant
            </th>
            {avecBillets ? <th scope="col">Billet</th> : null}
          </tr>
        </thead>
        <tbody>
          {donnees.lignes.map((ligne) => {
            const billet = billetsParPlace.get(ligne.place_id);
            const place = billet ?? placesParId.get(ligne.place_id);
            const categorieId = placesParId.get(ligne.place_id)?.categorie_id;
            const categorie =
              categorieId !== undefined ? categories.get(categorieId)?.nom : undefined;
            return (
              <tr key={ligne.place_id}>
                <td>
                  {place !== undefined ? libellePlace(place) : "Place"}
                  {categorie !== undefined ? ` (${categorie})` : null}
                </td>
                <td className={styleReservation.montant}>{formaterEuros(ligne.montant)}</td>
                {avecBillets ? (
                  <td>
                    {billet !== undefined ? (
                      <>
                        {LIBELLES_STATUT_BILLET[billet.statut]}{" "}
                        <Link to={`/billets/${billet.id}`}>
                          Voir le billet
                          <span className={styles.masque}> {libellePlace(billet)}</span>
                        </Link>
                      </>
                    ) : emissionEnCours ? (
                      "Émission en cours…"
                    ) : (
                      "Billet à venir"
                    )}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Total</th>
            <td className={styleReservation.montant}>{formaterEuros(donnees.montant_total)}</td>
            {avecBillets ? <td /> : null}
          </tr>
        </tfoot>
      </table>

      {donnees.statut === "CONFIRMEE" && billets.error !== null ? (
        <div className={styles.etat}>
          <Erreur probleme={billets.error} />
          <Bouton
            variante="secondaire"
            occupe={billets.isFetching}
            surClic={() => void billets.refetch()}
          >
            Relire mes billets
          </Bouton>
        </div>
      ) : donnees.statut === "CONFIRMEE" && billetsParPlace.size < nombreLignes ? (
        <p role="status">
          {emissionEnCours
            ? "Émission de vos billets en cours…"
            : "Vos billets sont en cours d'émission, ils arriveront aussi par e-mail."}
        </p>
      ) : null}

      <div className={styleReservation.actions}>
        <Link to="/billets">Mes billets</Link>
        <Link to="/commandes">Mes commandes</Link>
      </div>
    </div>
  );
}
