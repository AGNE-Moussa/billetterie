// E13 Nouvelle séance (route /organisateur/evenements/:evenementId/seances/nouvelle, rôle admin,
// BIL-022) : lieu, date et heure de début, catégories répétables (nom, prix en euros converti en
// centimes, rangs et leur nombre de places). Les règles sont celles de l'API : un 422 s'affiche
// sous chaque champ concerné (CA2), SHOW_START_IN_PAST sous la date, VENUE_NOT_FOUND sous le lieu.
// Succès : renvoi vers E12 ; les places sont créées ensuite par Billets, en asynchrone.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { creerSeance, lireEvenement, listerTousLesLieux } from "../../api/catalogue";
import type { CategorieCreation, SeanceCreation } from "../../api/genere/catalogue";
import { convertirErreur } from "../../api/problemes";
import { Bouton } from "../../composants/Bouton";
import { ChampFormulaire, type OptionChamp } from "../../composants/ChampFormulaire";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { Vide } from "../../composants/Vide";
import { useNotifications } from "../../notifications/notifications";
import { PageIntrouvable } from "../PageIntrouvable";
import styles from "../catalogue/PageCatalogue.module.css";
import { repartirErreurs } from "./erreursChamps";
import styleOrganisateur from "./Organisateur.module.css";

/** Bornes du contrat (`SeanceCreation.categories`, `CategorieCreation.rangs`). */
const CATEGORIES_MAX = 20;
const RANGS_MAX = 100;

/** Codes sans tableau `erreurs` rattachés à un champ du formulaire. */
const CHAMPS_PAR_CODE = { SHOW_START_IN_PAST: "debut", VENUE_NOT_FOUND: "lieu_id" } as const;

const CODES_INTROUVABLE = new Set(["EVENT_NOT_FOUND", "REQUETE_INVALIDE"]);

interface RangSaisi {
  cle: number;
  rang: string;
  nombrePlaces: string;
}

interface CategorieSaisie {
  cle: number;
  nom: string;
  prix: string;
  rangs: RangSaisi[];
}

/** Clés React des lignes répétables : un compteur suffit, elles ne quittent jamais l'écran. */
let derniereCle = 0;

function nouvelleCle(): number {
  derniereCle += 1;
  return derniereCle;
}

function nouveauRang(): RangSaisi {
  return { cle: nouvelleCle(), rang: "", nombrePlaces: "" };
}

function nouvelleCategorie(): CategorieSaisie {
  return { cle: nouvelleCle(), nom: "", prix: "", rangs: [nouveauRang()] };
}

/**
 * Prix saisi en euros (« 45 », « 45,50 », « 45.5 ») converti en centimes. Une saisie illisible
 * donne NaN, envoyé `null` : l'API la refuse en 422 sous le champ, comme toute autre règle.
 */
function versCentimes(saisie: string): number {
  const texte = saisie.replace(/[\s€]/g, "").replace(",", ".");
  return texte === "" ? Number.NaN : Math.round(Number(texte) * 100);
}

/** Valeur d'un champ `datetime-local` (heure locale) en ISO 8601 avec fuseau ; sinon telle quelle. */
function versDateHeure(saisie: string): string {
  const date = new Date(saisie);
  return saisie === "" || Number.isNaN(date.getTime()) ? saisie : date.toISOString();
}

function versCorps(lieuId: string, debut: string, categories: readonly CategorieSaisie[]) {
  return {
    lieu_id: lieuId,
    debut: versDateHeure(debut),
    categories: categories.map((categorie): CategorieCreation => ({
      nom: categorie.nom,
      prix: versCentimes(categorie.prix),
      rangs: categorie.rangs.map((rang) => ({
        rang: rang.rang,
        nombre_places: rang.nombrePlaces.trim() === "" ? Number.NaN : Number(rang.nombrePlaces),
      })),
    })),
  } satisfies SeanceCreation;
}

/** Noms des champs affichés, au format des erreurs de l'API (sans « body. »). */
function champsAffiches(categories: readonly CategorieSaisie[]): Set<string> {
  const champs = new Set(["lieu_id", "debut", "categories"]);
  categories.forEach((categorie, i) => {
    for (const suffixe of ["", ".nom", ".prix", ".rangs"]) {
      champs.add(`categories.${String(i)}${suffixe}`);
    }
    categorie.rangs.forEach((_, j) => {
      champs.add(`categories.${String(i)}.rangs.${String(j)}.rang`);
      champs.add(`categories.${String(i)}.rangs.${String(j)}.nombre_places`);
    });
  });
  return champs;
}

export function PageNouvelleSeance() {
  const { evenementId = "" } = useParams();
  const naviguer = useNavigate();
  const clientRequetes = useQueryClient();
  const { notifier } = useNotifications();

  const [lieuId, setLieuId] = useState("");
  const [debut, setDebut] = useState("");
  const [categories, setCategories] = useState<CategorieSaisie[]>(() => [nouvelleCategorie()]);

  const evenement = useQuery({
    queryKey: ["catalogue", "evenement", evenementId],
    queryFn: () => lireEvenement(evenementId),
  });
  const lieux = useQuery({
    queryKey: ["catalogue", "lieux", "tous"],
    queryFn: listerTousLesLieux,
  });

  const creation = useMutation({
    mutationFn: (corps: SeanceCreation) => creerSeance(evenementId, corps),
    onSuccess: () => {
      void clientRequetes.invalidateQueries({ queryKey: ["catalogue", "seances", evenementId] });
      notifier({
        type: "succes",
        message: "Séance programmée : ses places sont en cours de création.",
      });
      void naviguer(`/organisateur/evenements/${evenementId}`);
    },
  });

  const codeEvenement = evenement.error !== null ? convertirErreur(evenement.error).code : null;
  if (codeEvenement !== null && CODES_INTROUVABLE.has(codeEvenement)) {
    return <PageIntrouvable />;
  }

  const { parChamp, resume } = repartirErreurs(
    creation.error,
    champsAffiches(categories),
    CHAMPS_PAR_CODE,
  );
  const cheminEvenement = `/organisateur/evenements/${evenementId}`;

  /** Changement de structure (ajout, retrait) : les erreurs indexées ne correspondent plus. */
  const changerStructure = (suivantes: CategorieSaisie[]) => {
    creation.reset();
    setCategories(suivantes);
  };
  const modifierCategorie = (cle: number, modification: Partial<CategorieSaisie>) =>
    setCategories((courantes) =>
      courantes.map((c) => (c.cle === cle ? { ...c, ...modification } : c)),
    );
  const modifierRang = (cleCategorie: number, cleRang: number, modification: Partial<RangSaisi>) =>
    setCategories((courantes) =>
      courantes.map((c) =>
        c.cle === cleCategorie
          ? { ...c, rangs: c.rangs.map((r) => (r.cle === cleRang ? { ...r, ...modification } : r)) }
          : c,
      ),
    );

  const programmer = (evenementFormulaire: FormEvent<HTMLFormElement>) => {
    evenementFormulaire.preventDefault();
    if (creation.isPending) return;
    creation.mutate(versCorps(lieuId, debut, categories));
  };

  const titre = evenement.data?.donnees.nom;

  let contenu;
  if (lieux.error !== null) {
    contenu = (
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
    );
  } else if (lieux.isPending) {
    contenu = <Chargement libelle="Chargement des lieux…" />;
  } else if (lieux.data.length === 0) {
    contenu = (
      <Vide
        message="Aucun lieu : créez d'abord un lieu."
        action={<Link to="/organisateur/lieux">Créer un lieu</Link>}
      />
    );
  } else {
    const options: OptionChamp[] = [
      { valeur: "", libelle: "Choisir un lieu" },
      ...lieux.data.map((lieu) => ({ valeur: lieu.id, libelle: `${lieu.nom}, ${lieu.ville}` })),
    ];
    contenu = (
      // noValidate : la validation est celle de l'API, affichée champ par champ (CA2).
      <form className={styleOrganisateur.formulaire} onSubmit={programmer} noValidate>
        <ChampFormulaire
          type="select"
          libelle="Lieu"
          nom="lieu_id"
          obligatoire
          options={options}
          valeur={lieuId}
          surChanger={setLieuId}
          erreur={parChamp.get("lieu_id")}
        />
        <ChampFormulaire
          type="datetime-local"
          libelle="Début"
          nom="debut"
          obligatoire
          aide="Date et heure locales de début de la séance."
          valeur={debut}
          surChanger={setDebut}
          erreur={parChamp.get("debut")}
        />
        {parChamp.has("categories") ? (
          <p className={styleOrganisateur.erreurGroupe}>{parChamp.get("categories")}</p>
        ) : null}
        {categories.map((categorie, i) => {
          const numero = String(i + 1);
          const prefixe = `categories.${String(i)}`;
          const erreurCategorie = parChamp.get(prefixe) ?? parChamp.get(`${prefixe}.rangs`);
          return (
            <fieldset key={categorie.cle} className={styleOrganisateur.groupe}>
              <legend>Catégorie {numero}</legend>
              <div className={styleOrganisateur.ligne}>
                <ChampFormulaire
                  type="text"
                  libelle="Nom"
                  obligatoire
                  valeur={categorie.nom}
                  surChanger={(nom) => modifierCategorie(categorie.cle, { nom })}
                  erreur={parChamp.get(`${prefixe}.nom`)}
                />
                <ChampFormulaire
                  type="text"
                  libelle="Prix en euros"
                  obligatoire
                  aide="Par exemple 45 ou 45,50."
                  valeur={categorie.prix}
                  surChanger={(prix) => modifierCategorie(categorie.cle, { prix })}
                  erreur={parChamp.get(`${prefixe}.prix`)}
                />
              </div>
              {erreurCategorie !== undefined ? (
                <p className={styleOrganisateur.erreurGroupe}>{erreurCategorie}</p>
              ) : null}
              {categorie.rangs.map((rang, j) => {
                const numeroRang = String(j + 1);
                const prefixeRang = `${prefixe}.rangs.${String(j)}`;
                return (
                  <div key={rang.cle} className={styleOrganisateur.ligne}>
                    <ChampFormulaire
                      type="text"
                      libelle={`Rang ${numeroRang}`}
                      obligatoire
                      valeur={rang.rang}
                      surChanger={(valeur) =>
                        modifierRang(categorie.cle, rang.cle, { rang: valeur })
                      }
                      erreur={parChamp.get(`${prefixeRang}.rang`)}
                    />
                    <ChampFormulaire
                      type="number"
                      libelle={`Places du rang ${numeroRang}`}
                      obligatoire
                      valeur={rang.nombrePlaces}
                      surChanger={(valeur) =>
                        modifierRang(categorie.cle, rang.cle, { nombrePlaces: valeur })
                      }
                      erreur={parChamp.get(`${prefixeRang}.nombre_places`)}
                    />
                    <Bouton
                      variante="secondaire"
                      inactif={categorie.rangs.length <= 1}
                      surClic={() =>
                        changerStructure(
                          categories.map((c) =>
                            c.cle === categorie.cle
                              ? { ...c, rangs: c.rangs.filter((r) => r.cle !== rang.cle) }
                              : c,
                          ),
                        )
                      }
                    >
                      Retirer le rang {numeroRang}
                      <span className={styles.masque}> de la catégorie {numero}</span>
                    </Bouton>
                  </div>
                );
              })}
              <div className={styleOrganisateur.actions}>
                <Bouton
                  variante="secondaire"
                  inactif={categorie.rangs.length >= RANGS_MAX}
                  surClic={() =>
                    changerStructure(
                      categories.map((c) =>
                        c.cle === categorie.cle ? { ...c, rangs: [...c.rangs, nouveauRang()] } : c,
                      ),
                    )
                  }
                >
                  Ajouter un rang<span className={styles.masque}> à la catégorie {numero}</span>
                </Bouton>
                <Bouton
                  variante="secondaire"
                  inactif={categories.length <= 1}
                  surClic={() =>
                    changerStructure(categories.filter((c) => c.cle !== categorie.cle))
                  }
                >
                  Retirer la catégorie {numero}
                </Bouton>
              </div>
            </fieldset>
          );
        })}
        <div className={styleOrganisateur.actions}>
          <Bouton
            variante="secondaire"
            inactif={categories.length >= CATEGORIES_MAX}
            surClic={() => changerStructure([...categories, nouvelleCategorie()])}
          >
            Ajouter une catégorie
          </Bouton>
        </div>
        {resume !== null ? <Erreur probleme={resume} /> : null}
        <div className={styleOrganisateur.actions}>
          <Bouton type="submit" occupe={creation.isPending}>
            Programmer
          </Bouton>
          <Link to={cheminEvenement}>Annuler</Link>
        </div>
      </form>
    );
  }

  return (
    <div className={styles.page}>
      <p className={styles.retour}>
        <Link to={cheminEvenement}>Retour à {titre ?? "l'événement"}</Link>
      </p>
      <h1>Nouvelle séance</h1>
      {evenement.error !== null ? <Erreur probleme={evenement.error} /> : null}
      {contenu}
    </div>
  );
}
