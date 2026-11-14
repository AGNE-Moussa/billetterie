// E12 Gérer un événement (route /organisateur/evenements/:evenementId, rôle admin, BIL-022) :
// nom, description et séances paginées (page dans l'URL) avec date, lieu, catégories et état ;
// « Programmer une séance » et « Voir » par séance. Pas de « Modifier » : aucune route ne le
// permet (Q8 de docs/front/ecrans.md, hors périmètre).
import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { useId } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { lireEvenement, lireLieu, listerSeances, type Lecture } from "../../api/catalogue";
import type { Lieu, Seance } from "../../api/genere/catalogue";
import { convertirErreur } from "../../api/problemes";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { TableauPagine, type ColonneTableau } from "../../composants/TableauPagine";
import { Vide } from "../../composants/Vide";
import { formaterDateHeure, formaterEuros } from "../../format";
import { PageIntrouvable } from "../PageIntrouvable";
import { lirePage } from "../catalogue/filtres";
import styles from "../catalogue/PageCatalogue.module.css";
import styleOrganisateur from "./Organisateur.module.css";

/** Un lieu change rarement : relu au plus toutes les cinq minutes. */
const FRAICHEUR_LIEU_MS = 5 * 60 * 1000;

/** Codes qui signifient « cet événement n'existe pas » (identifiant inconnu ou mal formé). */
const CODES_INTROUVABLE = new Set(["EVENT_NOT_FOUND", "REQUETE_INVALIDE"]);

function estIntrouvable(erreur: unknown): boolean {
  if (erreur === null) return false;
  const { code } = convertirErreur(erreur);
  return code !== null && CODES_INTROUVABLE.has(code);
}

export function PageGererEvenement() {
  const { evenementId = "" } = useParams();
  const [parametres, setParametres] = useSearchParams();
  const page = lirePage(parametres);
  const idSeances = useId();
  const cheminNouvelleSeance = `/organisateur/evenements/${evenementId}/seances/nouvelle`;

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
    return <PageIntrouvable />;
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
      <p className={styles.retour}>
        <Link to="/organisateur">Retour à l'espace organisateur</Link>
      </p>
      {perimee ? <BandeauModeDegrade /> : null}
      {evenement.error !== null ? (
        <>
          <h1>Gérer un événement</h1>
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
          <h1>Gérer un événement</h1>
          <Chargement libelle="Chargement de l'événement…" />
        </>
      ) : (
        <>
          <h1>{evenement.data.donnees.nom}</h1>
          <p className={styles.descriptionComplete}>{evenement.data.donnees.description}</p>
        </>
      )}

      <section aria-labelledby={idSeances} className={styles.resultats}>
        <h2 id={idSeances} className={styles.titreResultats}>
          Séances
        </h2>
        <div className={styleOrganisateur.actions}>
          <Link to={cheminNouvelleSeance}>Programmer une séance</Link>
        </div>
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
          <Chargement libelle="Chargement des séances…" />
        ) : seances.data.donnees.total === 0 ? (
          <Vide
            message="Aucune séance."
            action={<Link to={cheminNouvelleSeance}>Programmer une séance</Link>}
          />
        ) : (
          <TableauPagine
            libelle="Séances de l'événement"
            colonnes={colonnesSeances(lieuxConnus, lieuxEnErreur)}
            page={seances.data.donnees}
            cleLigne={(seance) => seance.id}
            surChangerPage={changerPage}
            messageVide="Cette page de séances est vide."
            occupe={seances.isFetching && seances.isPlaceholderData}
          />
        )}
      </section>
    </div>
  );
}

function colonnesSeances(
  lieux: ReadonlyMap<string, Lecture<Lieu>>,
  lieuxEnErreur: ReadonlySet<string>,
): readonly ColonneTableau<Seance>[] {
  return [
    {
      entete: "Date",
      rendu: (seance) => <time dateTime={seance.debut}>{formaterDateHeure(seance.debut)}</time>,
    },
    {
      entete: "Lieu",
      rendu: (seance) => {
        const lieu = lieux.get(seance.lieu_id)?.donnees;
        if (lieu !== undefined) return `${lieu.nom}, ${lieu.ville}`;
        return lieuxEnErreur.has(seance.lieu_id) ? "Lieu indisponible" : "Chargement du lieu…";
      },
    },
    {
      entete: "Catégories",
      rendu: (seance) =>
        seance.annulee ? (
          <span className={styles.annulee}>Annulée</span>
        ) : (
          <ul className={styles.tarifs}>
            {seance.categories.map((categorie) => (
              <li key={categorie.id}>
                {categorie.nom} : {formaterEuros(categorie.prix)}
              </li>
            ))}
          </ul>
        ),
    },
    {
      entete: "Action",
      rendu: (seance) => (
        <Link to={`/organisateur/seances/${seance.id}`}>
          Voir<span className={styles.masque}> la séance du {formaterDateHeure(seance.debut)}</span>
        </Link>
      ),
    },
  ];
}
