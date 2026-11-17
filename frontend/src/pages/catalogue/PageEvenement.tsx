// E02 Fiche événement (route /evenements/:evenementId, BIL-019) : bannière (visuel généré), nom,
// description et séances paginées en cartes (page dans l'URL) avec date, lieu, tarifs et mention
// « Annulée ». Un lieu est lu une
// fois par identifiant distinct (cache TanStack Query). La disponibilité par séance n'est pas
// affichée : aucune route ne la donne (Q4 de docs/front/ecrans.md).
import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { useId } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router";

import { lireEvenement, lireLieu, listerSeances, type Lecture } from "../../api/catalogue";
import type { Lieu, Seance } from "../../api/genere/catalogue";
import { convertirErreur } from "../../api/problemes";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { Pagination } from "../../composants/Pagination";
import { Vide } from "../../composants/Vide";
import { VisuelEvenement } from "../../composants/VisuelEvenement";
import { formaterDateHeure, formaterEuros, morceauxDate } from "../../format";
import { lirePage } from "./filtres";
import type { EtatRetourCatalogue } from "./PageCatalogue";
import styles from "./PageCatalogue.module.css";

/** Un lieu change rarement : relu au plus toutes les cinq minutes. */
const FRAICHEUR_LIEU_MS = 5 * 60 * 1000;

/** Codes qui signifient « cet événement n'existe pas » (identifiant inconnu ou mal formé). */
const CODES_INTROUVABLE = new Set(["EVENT_NOT_FOUND", "REQUETE_INVALIDE"]);

function estIntrouvable(erreur: unknown): boolean {
  const { code } = convertirErreur(erreur);
  return code !== null && CODES_INTROUVABLE.has(code);
}

/** Chemin du catalogue à retrouver (filtres compris) si la fiche a été ouverte depuis lui. */
function cheminRetour(etat: unknown): string {
  if (typeof etat === "object" && etat !== null && "retourCatalogue" in etat) {
    const { retourCatalogue } = etat as EtatRetourCatalogue;
    if (typeof retourCatalogue === "string" && retourCatalogue.startsWith("?")) {
      return `/${retourCatalogue}`;
    }
  }
  return "/";
}

function LienRetour() {
  const { state } = useLocation();
  return (
    <p className={styles.retour}>
      <Link to={cheminRetour(state)}>Retour au catalogue</Link>
    </p>
  );
}

function EvenementIntrouvable() {
  return (
    <div className={styles.page}>
      <h1>Événement introuvable</h1>
      <p>Cet événement n'existe pas ou n'est plus proposé.</p>
      <LienRetour />
    </div>
  );
}

export function PageEvenement() {
  const { evenementId = "" } = useParams();
  const [parametres, setParametres] = useSearchParams();
  const page = lirePage(parametres);
  const idSeances = useId();

  const evenement = useQuery({
    queryKey: ["catalogue", "evenement", evenementId],
    queryFn: () => lireEvenement(evenementId),
  });
  const seances = useQuery({
    queryKey: ["catalogue", "seances", evenementId, page],
    queryFn: () => listerSeances(evenementId, page),
    placeholderData: keepPreviousData,
  });
  const idsLieux = [...new Set(seances.data?.donnees.elements.map((s) => s.lieu_id) ?? [])];
  const lieux = useQueries({
    queries: idsLieux.map((lieuId) => ({
      queryKey: ["catalogue", "lieu", lieuId],
      queryFn: () => lireLieu(lieuId),
      staleTime: FRAICHEUR_LIEU_MS,
    })),
  });

  if (estIntrouvable(evenement.error) || estIntrouvable(seances.error)) {
    return <EvenementIntrouvable />;
  }

  const lieuxConnus = new Map<string, Lecture<Lieu>>();
  const lieuxEnErreur = new Set<string>();
  lieux.forEach((lecture, index) => {
    const lieuId = idsLieux[index];
    if (lieuId === undefined) return;
    if (lecture.data !== undefined) lieuxConnus.set(lieuId, lecture.data);
    else if (lecture.error !== null) lieuxEnErreur.add(lieuId);
  });
  const perimee =
    evenement.data?.perimee === true ||
    seances.data?.perimee === true ||
    [...lieuxConnus.values()].some((lecture) => lecture.perimee);

  const changerPage = (numero: number) => {
    const suivants = new URLSearchParams(parametres);
    if (numero > 1) suivants.set("page", String(numero));
    else suivants.delete("page");
    setParametres(suivants);
  };

  return (
    <div className={styles.page}>
      <LienRetour />
      {perimee ? <BandeauModeDegrade /> : null}
      {evenement.error !== null ? (
        <>
          <h1>Fiche événement</h1>
          <div className={styles.etat}>
            <Erreur probleme={evenement.error} />
            <Bouton
              variante="secondaire"
              occupe={evenement.isFetching}
              surClic={() => void evenement.refetch()}
            >
              Réessayer
            </Bouton>
          </div>
        </>
      ) : evenement.isPending ? (
        <>
          <h1>Fiche événement</h1>
          <Chargement libelle="Chargement de l'événement…" forme="bloc" />
        </>
      ) : (
        <>
          <div className={styles.banniere}>
            <VisuelEvenement
              graine={evenementId}
              nom={evenement.data.donnees.nom}
              format="banniere"
            />
            <div className={styles.banniereTexte}>
              <h1>{evenement.data.donnees.nom}</h1>
            </div>
          </div>
          <p className={styles.descriptionComplete}>{evenement.data.donnees.description}</p>
        </>
      )}

      <section aria-labelledby={idSeances} className={styles.resultats}>
        <h2 id={idSeances} className={styles.titreResultats}>
          Séances
        </h2>
        {seances.error !== null ? (
          <div className={styles.etat}>
            <Erreur probleme={seances.error} />
            <Bouton
              variante="secondaire"
              occupe={seances.isFetching}
              surClic={() => void seances.refetch()}
            >
              Réessayer
            </Bouton>
          </div>
        ) : seances.isPending ? (
          <Chargement libelle="Chargement des séances…" forme="lignes" />
        ) : seances.data.donnees.total === 0 ? (
          <Vide
            message="Aucune séance programmée pour l'instant."
            action={<Link to="/">Voir les autres événements</Link>}
          />
        ) : seances.data.donnees.elements.length === 0 ? (
          <Vide message="Cette page de séances est vide." />
        ) : (
          <>
            <ul
              className={styles.seances}
              aria-label="Séances de l'événement"
              aria-busy={seances.isFetching && seances.isPlaceholderData ? true : undefined}
            >
              {seances.data.donnees.elements.map((seance) => (
                <li key={seance.id}>
                  <CarteSeance
                    seance={seance}
                    lieu={libelleLieu(seance, lieuxConnus, lieuxEnErreur)}
                  />
                </li>
              ))}
            </ul>
            <Pagination
              page={seances.data.donnees.page}
              size={seances.data.donnees.size}
              total={seances.data.donnees.total}
              surChangerPage={changerPage}
              occupe={seances.isFetching && seances.isPlaceholderData}
            />
          </>
        )}
      </section>
    </div>
  );
}

function libelleLieu(
  seance: Seance,
  lieux: ReadonlyMap<string, Lecture<Lieu>>,
  lieuxEnErreur: ReadonlySet<string>,
): string {
  const lieu = lieux.get(seance.lieu_id)?.donnees;
  if (lieu !== undefined) return `${lieu.nom}, ${lieu.ville}`;
  return lieuxEnErreur.has(seance.lieu_id) ? "Lieu indisponible" : "Chargement du lieu…";
}

/** Séance en carte : pastille de date, date complète, lieu, tarifs, puis « Choisir » ou « Annulée ». */
function CarteSeance({ seance, lieu }: { seance: Seance; lieu: string }) {
  const idTitre = useId();
  const { jourSemaine, jour, mois } = morceauxDate(seance.debut);
  return (
    <article
      className={`${styles.seance ?? ""} ${seance.annulee ? (styles.seanceAnnulee ?? "") : ""}`}
      aria-labelledby={idTitre}
    >
      <div className={styles.pastilleDate} aria-hidden="true">
        <span className={styles.pastilleMois}>{jourSemaine}</span>
        <span className={styles.pastilleJour}>{jour}</span>
        <span className={styles.pastilleMois}>{mois}</span>
      </div>
      <div className={styles.infosSeance}>
        <h3 id={idTitre}>
          <time dateTime={seance.debut}>{formaterDateHeure(seance.debut)}</time>
        </h3>
        <p className={styles.lieu}>{lieu}</p>
        <Tarifs seance={seance} />
      </div>
      <div className={styles.actionSeance}>
        {seance.annulee ? (
          <span className={`${styles.badge ?? ""} ${styles.annulee ?? ""}`}>Annulée</span>
        ) : (
          <Link to={`/seances/${seance.id}`} className={styles.lienAction}>
            Choisir
            <span className={styles.masque}> la séance du {formaterDateHeure(seance.debut)}</span>
          </Link>
        )}
      </div>
    </article>
  );
}

function Tarifs({ seance }: { seance: Seance }) {
  if (seance.categories.length === 0) {
    return <p className={styles.prixMin}>Tarifs à venir</p>;
  }
  const minimum = Math.min(...seance.categories.map((categorie) => categorie.prix));
  return (
    <>
      <p className={styles.prixMin}>À partir de {formaterEuros(minimum)}</p>
      <ul className={styles.tarifs}>
        {seance.categories.map((categorie) => (
          <li key={categorie.id}>
            {categorie.nom} : {formaterEuros(categorie.prix)}
          </li>
        ))}
      </ul>
    </>
  );
}
