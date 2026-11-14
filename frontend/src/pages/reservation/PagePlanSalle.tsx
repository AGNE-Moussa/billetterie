// E03 Séance et plan de salle (route /seances/:seanceId, BIL-020). Public pour consulter ; seul
// « Réserver » demande un client connecté (rôle customer), sinon connexion Keycloak avec retour
// sur la même URL, sélection comprise (`?places=`). Réserver appelle `creerCommande` sans carte
// (commande EN_ATTENTE, places verrouillées jusqu'à `expire_le`), puis mène au paiement (E04).
// Place prise entre-temps (409 SEAT_ALREADY_TAKEN, CA1) : message, plan relu, sélection gardée
// sans la place perdue, page intacte.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useRef } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";

import { listerToutesLesPlaces } from "../../api/billets";
import { lireEvenement, lireLieu, lireSeanceParId } from "../../api/catalogue";
import { reserverPlaces } from "../../api/commandes";
import type { Place } from "../../api/genere/billets";
import type { Commande } from "../../api/genere/commandes";
import { convertirErreur, MESSAGE_GENERIQUE } from "../../api/problemes";
import { useSession } from "../../auth/session";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { Vide } from "../../composants/Vide";
import { formaterDateHeure, formaterEuros } from "../../format";
import { useNotifications } from "../../notifications/notifications";
import styles from "../catalogue/PageCatalogue.module.css";
import {
  avecSelection,
  categoriesParId,
  cleCommande,
  clePlaces,
  libelleCourt,
  lireSelection,
  PLACES_PAR_COMMANDE_MAX,
} from "./places";
import { LegendePlan, PlanSalle } from "./PlanSalle";
import styleReservation from "./Reservation.module.css";

/** Un lieu change rarement : relu au plus toutes les cinq minutes. */
const FRAICHEUR_LIEU_MS = 5 * 60 * 1000;

/** Codes qui signifient « cette séance n'existe pas » (identifiant inconnu ou mal formé). */
const CODES_INTROUVABLE = new Set(["SHOW_NOT_FOUND", "REQUETE_INVALIDE"]);

/** Codes après lesquels le plan est relu : une place a changé d'état ou n'existe plus. */
const CODES_PLAN_PERIME = new Set(["SEAT_ALREADY_TAKEN", "SEAT_NOT_FOUND"]);

function codeDe(erreur: unknown): string | null {
  return erreur === null ? null : convertirErreur(erreur).code;
}

/** Réservation qui n'a pas abouti à une commande EN_ATTENTE (rejeu d'une commande expirée). */
class ReservationNonAboutie extends Error {}

function SeanceIntrouvable() {
  return (
    <div className={styles.page}>
      <h1>Séance introuvable</h1>
      <p>Cette séance n'existe pas ou n'est plus proposée.</p>
      <p className={styles.retour}>
        <Link to="/">Retour au catalogue</Link>
      </p>
    </div>
  );
}

function MessageErreurReservation({ erreur }: { erreur: unknown }) {
  if (erreur instanceof ReservationNonAboutie) {
    return (
      <div role="alert" className={styleReservation.alerte}>
        <p>
          <strong>La réservation n'a pas abouti.</strong>
        </p>
        <p>Le plan a été mis à jour ; vérifiez votre sélection puis réessayez.</p>
      </div>
    );
  }
  const code = codeDe(erreur);
  if (code === "SEAT_ALREADY_TAKEN") {
    return (
      <div role="alert" className={styleReservation.alerte}>
        <p>
          <strong>Une place vient d'être prise.</strong>
        </p>
        <p>
          Le plan a été mis à jour : la place perdue est retirée de votre sélection, les autres sont
          conservées. Choisissez une autre place si besoin, puis réservez à nouveau.
        </p>
      </div>
    );
  }
  if (code !== null && code.endsWith("_INDISPONIBLE")) {
    return (
      <div className={styleReservation.alerte}>
        <p>Achat momentanément impossible, la consultation reste possible.</p>
        <Erreur probleme={erreur} />
      </div>
    );
  }
  return (
    <div className={styleReservation.alerte}>
      <Erreur probleme={erreur} />
    </div>
  );
}

export function PagePlanSalle() {
  const { seanceId = "" } = useParams();
  const [parametres, setParametres] = useSearchParams();
  const { pathname, search } = useLocation();
  const naviguer = useNavigate();
  const clientRequetes = useQueryClient();
  const { notifier } = useNotifications();
  const session = useSession();
  const idPlan = useId();
  // Idempotency-Key de la tentative en cours, gardée pour rejouer la même sélection après une
  // panne réseau ou une requête encore en cours ; renouvelée sinon.
  const tentative = useRef<{ selection: string; cle: string } | null>(null);

  const seance = useQuery({
    queryKey: ["catalogue", "seance", seanceId],
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

  const reservation = useMutation({
    mutationFn: async ({ ids, cle }: { ids: string[]; cle: string }): Promise<Commande> => {
      const commande = await reserverPlaces(seanceId, ids, cle);
      if (commande.statut !== "EN_ATTENTE") {
        throw new ReservationNonAboutie();
      }
      return commande;
    },
    onSuccess: (commande) => {
      tentative.current = null;
      clientRequetes.setQueryData(cleCommande(commande.id), commande);
      void clientRequetes.invalidateQueries({ queryKey: clePlaces(seanceId) });
      void naviguer(`/commandes/${commande.id}/paiement`);
    },
    onError: (erreur) => {
      const code = codeDe(erreur);
      // Rejouer la même clé n'a de sens que si la première requête a pu ne pas aboutir.
      if (
        erreur instanceof ReservationNonAboutie ||
        (code !== null && code !== "REQUEST_IN_PROGRESS")
      ) {
        tentative.current = null;
      }
      if (
        erreur instanceof ReservationNonAboutie ||
        (code !== null && CODES_PLAN_PERIME.has(code))
      ) {
        // Plan relu, puis places devenues indisponibles retirées de l'URL : la sélection garde
        // les autres places (CA1).
        void places.refetch().then(({ data }) => {
          if (data === undefined) return;
          const libres = new Set(data.filter((place) => place.disponible).map((p) => p.id));
          setParametres(
            (actuels) =>
              avecSelection(
                actuels,
                lireSelection(actuels).filter((id) => libres.has(id)),
              ),
            { replace: true },
          );
        });
      }
    },
  });

  if (CODES_INTROUVABLE.has(codeDe(seance.error) ?? "")) {
    return <SeanceIntrouvable />;
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

  const donneesSeance = seance.data.donnees;
  const lectureSeule = donneesSeance.annulee;
  const categories = categoriesParId(donneesSeance.categories);
  const indicesCategories = new Map(
    donneesSeance.categories.map((categorie, indice) => [categorie.id, indice]),
  );
  const perimee =
    seance.data.perimee || evenement.data?.perimee === true || lieu.data?.perimee === true;

  // Sélection effective : places de l'URL encore libres (une place perdue en sort d'elle-même
  // dès que le plan est relu).
  const selectionUrl = lireSelection(parametres);
  const placesParId = new Map((places.data ?? []).map((place) => [place.id, place]));
  const selection =
    places.data === undefined
      ? selectionUrl
      : selectionUrl.filter((id) => placesParId.get(id)?.disponible === true);
  const placesChoisies = selection
    .map((id) => placesParId.get(id))
    .filter((place): place is Place => place !== undefined);
  const total = placesChoisies.reduce(
    (somme, place) => somme + (categories.get(place.categorie_id)?.prix ?? 0),
    0,
  );

  const basculer = (place: Place) => {
    reservation.reset();
    if (selection.includes(place.id)) {
      setParametres(
        avecSelection(
          parametres,
          selection.filter((id) => id !== place.id),
        ),
        { replace: true },
      );
      return;
    }
    if (selection.length >= PLACES_PAR_COMMANDE_MAX) {
      notifier({
        type: "info",
        message: `${String(PLACES_PAR_COMMANDE_MAX)} places au plus par commande.`,
      });
      return;
    }
    setParametres(avecSelection(parametres, [...selection, place.id]), { replace: true });
  };

  const reserver = () => {
    if (selection.length === 0) return;
    const cleSelection = selection.join(",");
    if (tentative.current?.selection !== cleSelection) {
      tentative.current = { selection: cleSelection, cle: crypto.randomUUID() };
    }
    reservation.mutate({ ids: selection, cle: tentative.current.cle });
  };

  const seConnecterPourReserver = () => {
    void session.seConnecter(`${pathname}${search}`).then((lancee) => {
      if (!lancee) notifier({ type: "erreur", message: MESSAGE_GENERIQUE });
    });
  };

  let action;
  if (lectureSeule) {
    action = <p>Séance annulée : le plan reste consultable, aucune réservation possible.</p>;
  } else if (session.statut === "chargement") {
    action = <Chargement libelle="Chargement de la session…" />;
  } else if (session.statut === "non-connecte") {
    action = (
      <Bouton surClic={seConnecterPourReserver} inactif={selection.length === 0}>
        Se connecter pour réserver
      </Bouton>
    );
  } else if (!session.roles.includes("customer")) {
    action = <p>Réservé aux clients.</p>;
  } else {
    action = (
      <Bouton surClic={reserver} inactif={selection.length === 0} occupe={reservation.isPending}>
        {selection.length > 1 ? "Réserver ces places" : "Réserver cette place"}
      </Bouton>
    );
  }

  return (
    <div className={styles.page}>
      <p className={styles.retour}>
        <Link to={`/evenements/${donneesSeance.evenement_id}`}>Retour à l'événement</Link>
      </p>
      {perimee ? <BandeauModeDegrade /> : null}
      <div className={styleReservation.entete}>
        <h1>{evenement.data?.donnees.nom ?? "Séance"}</h1>
        <p className={styleReservation.sousTitre}>
          <time dateTime={donneesSeance.debut}>{formaterDateHeure(donneesSeance.debut)}</time>
          {lieu.data !== undefined
            ? ` - ${lieu.data.donnees.nom}, ${lieu.data.donnees.ville}`
            : lieu.error !== null
              ? " - Lieu indisponible"
              : null}
          {lectureSeule ? <span className={styles.annulee}> - Annulée</span> : null}
        </p>
      </div>

      <section aria-labelledby={idPlan} className={styles.resultats}>
        <h2 id={idPlan} className={styles.titreResultats}>
          Choisissez vos places
        </h2>
        {places.error !== null && places.data === undefined ? (
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
        ) : places.isPending ? (
          <Chargement libelle="Chargement du plan de salle…" />
        ) : places.data.length === 0 ? (
          <Vide
            message="Les places de cette séance sont en cours de création."
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
        ) : (
          <>
            <LegendePlan
              categories={donneesSeance.categories}
              indicesCategories={indicesCategories}
            />
            <PlanSalle
              places={places.data}
              categories={categories}
              indicesCategories={indicesCategories}
              selection={selection}
              lectureSeule={lectureSeule}
              surBasculer={basculer}
            />
            {reservation.error !== null ? (
              <MessageErreurReservation erreur={reservation.error} />
            ) : null}
            <div className={styleReservation.recapitulatif}>
              <p aria-live="polite">
                {placesChoisies.length === 0
                  ? "Aucune place sélectionnée."
                  : `Sélection : ${placesChoisies.map(libelleCourt).join(", ")} - ${formaterEuros(total)}`}{" "}
                ({placesChoisies.length} {placesChoisies.length > 1 ? "places" : "place"} sur{" "}
                {PLACES_PAR_COMMANDE_MAX})
              </p>
              <div className={styleReservation.actions}>
                {action}
                <Bouton
                  variante="secondaire"
                  occupe={places.isFetching}
                  surClic={() => void places.refetch()}
                >
                  Rafraîchir le plan
                </Bouton>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
