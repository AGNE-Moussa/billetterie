// État commun « chargement » : role="status", « Chargement… » par défaut.

export interface ProprietesChargement {
  libelle?: string;
}

export function Chargement({ libelle = "Chargement…" }: ProprietesChargement) {
  return <p role="status">{libelle}</p>;
}
