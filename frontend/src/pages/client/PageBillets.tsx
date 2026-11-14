// E07 Mes billets (route /billets?page=, rôle customer, BIL-021) : billets de l'appelant en
// cartes paginées (page dans l'URL) : événement, date, lieu, place, statut, date d'émission, et
// lien vers E08. La liste est filtrée par le back sur le jeton, jamais par un paramètre.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useId } from "react";
import { Link, useSearchParams } from "react-router";

import { listerBillets } from "../../api/billets";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { Carte } from "../../composants/Carte";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { Pagination } from "../../composants/Pagination";
import { Vide } from "../../composants/Vide";
import { formaterDateHeure } from "../../format";
import { lirePage } from "../catalogue/filtres";
import styles from "../catalogue/PageCatalogue.module.css";
import { libellePlace } from "../reservation/places";
import { LIBELLES_STATUT_BILLET } from "./libelles";
import { descriptionSeance, useInfosSeances } from "./seances";

export function PageBillets() {
  const [parametres, setParametres] = useSearchParams();
  const page = lirePage(parametres);
  const idListe = useId();

  const billets = useQuery({
    queryKey: ["billets", "liste", page],
    queryFn: () => listerBillets(page),
    placeholderData: keepPreviousData,
  });
  const infos = useInfosSeances((billets.data?.elements ?? []).map((billet) => billet.seance_id));
  const perimee = [...infos.values()].some((info) => info.perimee);

  const changerPage = (numero: number) => {
    const suivants = new URLSearchParams(parametres);
    if (numero > 1) suivants.set("page", String(numero));
    else suivants.delete("page");
    setParametres(suivants);
  };

  return (
    <div className={styles.page}>
      <h1 id={idListe}>Mes billets</h1>
      {perimee ? <BandeauModeDegrade /> : null}
      {billets.error !== null ? (
        <div className={styles.etat}>
          <Erreur probleme={billets.error} />
          <Bouton
            variante="secondaire"
            occupe={billets.isFetching}
            surClic={() => void billets.refetch()}
          >
            Réessayer
          </Bouton>
        </div>
      ) : billets.isPending ? (
        <Chargement libelle="Chargement de vos billets…" />
      ) : billets.data.total === 0 ? (
        <Vide
          message="Aucun billet pour l'instant."
          action={<Link to="/">Voir les événements</Link>}
        />
      ) : (
        <>
          <ul
            className={styles.liste}
            aria-labelledby={idListe}
            aria-busy={billets.isFetching && billets.isPlaceholderData ? true : undefined}
          >
            {billets.data.elements.map((billet) => {
              const info = infos.get(billet.seance_id);
              return (
                <li key={billet.id}>
                  <Carte
                    titre={info?.evenement?.nom ?? "Billet"}
                    actions={
                      <Link to={`/billets/${billet.id}`}>
                        {billet.statut === "EMIS" ? "Afficher le QR code" : "Voir"}
                        <span className={styles.masque}> du billet {libellePlace(billet)}</span>
                      </Link>
                    }
                  >
                    <p>{descriptionSeance(info)}</p>
                    <p>{libellePlace(billet)}</p>
                    <p>
                      <strong>{LIBELLES_STATUT_BILLET[billet.statut]}</strong>
                    </p>
                    <p>
                      Émis le{" "}
                      <time dateTime={billet.emis_le}>{formaterDateHeure(billet.emis_le)}</time>
                    </p>
                  </Carte>
                </li>
              );
            })}
          </ul>
          <Pagination
            page={billets.data.page}
            size={billets.data.size}
            total={billets.data.total}
            surChangerPage={changerPage}
            occupe={billets.isFetching && billets.isPlaceholderData}
          />
        </>
      )}
    </div>
  );
}
