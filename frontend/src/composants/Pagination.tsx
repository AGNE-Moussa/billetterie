// Pagination contrôlée d'une liste qui n'est pas un tableau (cartes) : mêmes boutons et même
// position annoncée que TableauPagine. Les boutons aux bornes ou pendant l'état occupé sont
// inactifs (aria-disabled, focus conservé).
import { Bouton } from "./Bouton";
import styles from "./Pagination.module.css";

export interface ProprietesPagination {
  page: number;
  size: number;
  total: number;
  surChangerPage: (numero: number) => void;
  occupe?: boolean;
}

/** Nombre de pages de la collection, au moins 1. */
export function nombreDePages(size: number, total: number): number {
  return size > 0 ? Math.max(1, Math.ceil(total / size)) : 1;
}

export function Pagination({
  page,
  size,
  total,
  surChangerPage,
  occupe = false,
}: ProprietesPagination) {
  const pages = nombreDePages(size, total);
  return (
    <nav aria-label="Pagination" className={styles.pagination}>
      <Bouton
        variante="secondaire"
        inactif={occupe || page <= 1}
        surClic={() => surChangerPage(page - 1)}
      >
        Page précédente
      </Bouton>
      <p className={styles.position} aria-live="polite">
        {`Page ${String(page)} sur ${String(pages)}`}
      </p>
      <Bouton
        variante="secondaire"
        inactif={occupe || page >= pages}
        surClic={() => surChangerPage(page + 1)}
      >
        Page suivante
      </Bouton>
    </nav>
  );
}
