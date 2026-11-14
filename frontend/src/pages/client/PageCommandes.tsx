// E06 Mes commandes (route /commandes?page=, rôle customer, BIL-021) : commandes de l'appelant,
// paginées (page dans l'URL). La liste est filtrée par le back sur le jeton, jamais par un
// paramètre du front. Séance illisible : ligne gardée avec « Séance indisponible ».
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import { listerCommandes } from "../../api/commandes";
import type { Commande } from "../../api/genere/commandes";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { TableauPagine, type ColonneTableau } from "../../composants/TableauPagine";
import { Vide } from "../../composants/Vide";
import { formaterDateHeure, formaterEuros } from "../../format";
import { lirePage } from "../catalogue/filtres";
import styles from "../catalogue/PageCatalogue.module.css";
import { LIBELLES_STATUT_COMMANDE } from "./libelles";
import { descriptionSeance, useInfosSeances, type InfosSeance } from "./seances";

export function PageCommandes() {
  const [parametres, setParametres] = useSearchParams();
  const page = lirePage(parametres);

  const commandes = useQuery({
    queryKey: ["commandes", "liste", page],
    queryFn: () => listerCommandes(page),
    placeholderData: keepPreviousData,
  });
  const infos = useInfosSeances(
    (commandes.data?.elements ?? []).map((commande) => commande.seance_id),
  );
  const perimee = [...infos.values()].some((info) => info.perimee);

  const changerPage = (numero: number) => {
    const suivants = new URLSearchParams(parametres);
    if (numero > 1) suivants.set("page", String(numero));
    else suivants.delete("page");
    setParametres(suivants);
  };

  return (
    <div className={styles.page}>
      <h1>Mes commandes</h1>
      {perimee ? <BandeauModeDegrade /> : null}
      {commandes.error !== null ? (
        <div className={styles.etat}>
          <Erreur probleme={commandes.error} />
          <Bouton
            variante="secondaire"
            occupe={commandes.isFetching}
            surClic={() => void commandes.refetch()}
          >
            Réessayer
          </Bouton>
        </div>
      ) : commandes.isPending ? (
        <Chargement libelle="Chargement de vos commandes…" />
      ) : commandes.data.total === 0 ? (
        <Vide
          message="Vous n'avez pas encore de commande."
          action={<Link to="/">Voir les événements</Link>}
        />
      ) : (
        <TableauPagine
          libelle="Mes commandes"
          colonnes={colonnesCommandes(infos)}
          page={commandes.data}
          cleLigne={(commande) => commande.id}
          surChangerPage={changerPage}
          messageVide="Cette page de commandes est vide."
          occupe={commandes.isFetching && commandes.isPlaceholderData}
        />
      )}
    </div>
  );
}

function colonnesCommandes(
  infos: ReadonlyMap<string, InfosSeance>,
): readonly ColonneTableau<Commande>[] {
  return [
    {
      entete: "Date",
      rendu: (commande) => (
        <time dateTime={commande.cree_le}>{formaterDateHeure(commande.cree_le)}</time>
      ),
    },
    { entete: "Séance", rendu: (commande) => descriptionSeance(infos.get(commande.seance_id)) },
    { entete: "Places", rendu: (commande) => String(commande.lignes.length) },
    { entete: "Total", rendu: (commande) => formaterEuros(commande.montant_total) },
    { entete: "Statut", rendu: (commande) => LIBELLES_STATUT_COMMANDE[commande.statut] },
    {
      entete: "Action",
      rendu: (commande) =>
        commande.statut === "EN_ATTENTE" ? (
          <Link to={`/commandes/${commande.id}/paiement`}>
            Payer
            <span className={styles.masque}>
              {" "}
              la commande du {formaterDateHeure(commande.cree_le)}
            </span>
          </Link>
        ) : (
          <Link to={`/commandes/${commande.id}`}>
            Voir
            <span className={styles.masque}>
              {" "}
              la commande du {formaterDateHeure(commande.cree_le)}
            </span>
          </Link>
        ),
    },
  ];
}
