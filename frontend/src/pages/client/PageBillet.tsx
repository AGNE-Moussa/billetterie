// E08 Billet et QR code (route /billets/:billetId, rôle customer, BIL-021) : événement, date,
// lieu, place et statut ; QR code dessiné côté client à partir de `qr_code` (identifiant signé,
// aucune donnée lisible), jamais pour un billet ANNULE. Billet d'un autre client : même rendu
// qu'une page introuvable (TICKET_NOT_FOUND), jamais « Accès refusé ».
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { lireBillet } from "../../api/billets";
import { convertirErreur } from "../../api/problemes";
import { BandeauModeDegrade } from "../../composants/BandeauModeDegrade";
import { Bouton } from "../../composants/Bouton";
import { Chargement } from "../../composants/Chargement";
import { Erreur } from "../../composants/Erreur";
import { QrCode } from "../../composants/QrCode";
import { formaterDateHeure } from "../../format";
import { PageIntrouvable } from "../PageIntrouvable";
import styles from "../catalogue/PageCatalogue.module.css";
import { libellePlace } from "../reservation/places";
import styleReservation from "../reservation/Reservation.module.css";
import { cleBillet, LIBELLES_STATUT_BILLET } from "./libelles";
import { useInfosSeances } from "./seances";

/** Codes qui signifient « ce billet n'existe pas pour vous » (même rendu que 404). */
const CODES_INTROUVABLE = new Set(["TICKET_NOT_FOUND", "REQUETE_INVALIDE"]);

function LienRetour() {
  return (
    <p className={styles.retour}>
      <Link to="/billets">Retour à mes billets</Link>
    </p>
  );
}

export function PageBillet() {
  const { billetId = "" } = useParams();

  const billet = useQuery({
    queryKey: cleBillet(billetId),
    queryFn: () => lireBillet(billetId),
  });
  const seanceId = billet.data?.seance_id;
  const infos = useInfosSeances(seanceId !== undefined ? [seanceId] : []).get(seanceId ?? "");

  const code = billet.error !== null ? convertirErreur(billet.error).code : null;
  if (code !== null && CODES_INTROUVABLE.has(code)) {
    return <PageIntrouvable />;
  }
  if (billet.error !== null) {
    return (
      <div className={styles.page}>
        <LienRetour />
        <h1>Billet</h1>
        <div className={styles.etat}>
          <Erreur probleme={billet.error} />
          <Bouton
            variante="secondaire"
            occupe={billet.isFetching}
            surClic={() => void billet.refetch()}
          >
            Réessayer
          </Bouton>
        </div>
      </div>
    );
  }
  if (billet.isPending) {
    return (
      <div className={styles.page}>
        <LienRetour />
        <h1>Billet</h1>
        <Chargement libelle="Chargement du billet…" />
      </div>
    );
  }

  const donnees = billet.data;
  const place = libellePlace(donnees);
  const seance = infos?.seance;
  const lieu = infos?.lieu;

  return (
    <div className={styles.page}>
      <LienRetour />
      {infos?.perimee === true ? <BandeauModeDegrade /> : null}
      <div className={styleReservation.entete}>
        <h1>{infos?.evenement?.nom ?? "Billet"}</h1>
        <p className={styleReservation.sousTitre}>
          {seance !== undefined ? (
            <time dateTime={seance.debut}>{formaterDateHeure(seance.debut)}</time>
          ) : infos?.enErreur === true ? (
            "Séance indisponible"
          ) : (
            "Chargement de la séance…"
          )}
          {lieu !== undefined ? ` - ${lieu.nom}, ${lieu.adresse}, ${lieu.ville}` : null}
        </p>
        <p>{place}</p>
      </div>

      {donnees.statut === "EMIS" ? (
        <figure>
          <QrCode valeur={donnees.qr_code} libelle={`QR code du billet ${place.toLowerCase()}`} />
          <figcaption>
            {LIBELLES_STATUT_BILLET[donnees.statut]} - émis le{" "}
            <time dateTime={donnees.emis_le}>{formaterDateHeure(donnees.emis_le)}</time>
          </figcaption>
        </figure>
      ) : (
        <div role="alert" className={styleReservation.alerte}>
          <p>
            <strong>Billet annulé : séance annulée et commande remboursée.</strong>
          </p>
        </div>
      )}

      <p>
        <Link to={`/commandes/${donnees.commande_id}`}>Voir la commande</Link>
      </p>
    </div>
  );
}
