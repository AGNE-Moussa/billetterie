// Salle d'attente (E16, BIL-023) contre la plateforme démarrée. Seule la séance « Soirée jazz »
// du jeu de démonstration est sous file (SEANCES_SOUS_FILE, liste fixe de la configuration) : une
// séance créée par le test ne peut pas l'être. Configuration par défaut de compose.yaml : vagues
// de 50 admis toutes les 10 s, admission valable 600 s.
//
// Conséquences, assumées par ce parcours :
// - client.test, seul dans la file, est admis à la vague suivante (10 s au plus) : la position
//   n'est visible que quelques secondes, et l'admission est attendue 30 s au plus ;
// - un client déjà admis le reste 600 s : si un passage précédent l'a admis il y a moins de
//   10 minutes, `entrerFile` répond ADMIS d'emblée et la position n'est pas observable ; le test
//   est alors marqué « ignoré » avec ce motif, plutôt que de réussir sans rien vérifier.
import { expect, test, type Page, type Response } from "@playwright/test";

import { CLIENT_TEST, seConnecterSurKeycloak } from "./utilisateursDeTest";

const SOIREE_JAZZ = "6b1f0c2e-4d5a-4e8b-9c11-0d0e0b000005";

interface PositionFile {
  statut: "EN_ATTENTE" | "ADMIS";
  position: number | null;
}

/** Prochaine réponse de `entrerFile` (POST /api/v1/queues/{seance}/position). */
function prochaineEntreeFile(page: Page): Promise<Response> {
  return page.waitForResponse(
    (reponse) =>
      reponse.request().method() === "POST" &&
      reponse.url().includes(`/api/v1/queues/${SOIREE_JAZZ}/position`),
  );
}

test("test_la_salle_d_attente_affiche_la_position_et_un_rafraichissement_la_conserve", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await seConnecterSurKeycloak(page, CLIENT_TEST);
  await expect(page.getByText(CLIENT_TEST.nom, { exact: true })).toBeVisible();

  const entree = prochaineEntreeFile(page);
  await page.goto(`/seances/${SOIREE_JAZZ}/attente`);
  const premiere = await entree;
  // 201 à la première entrée, 200 si le client était déjà dans la file (contrat entrerFile).
  expect([200, 201], "entrerFile sur la séance sous file").toContain(premiere.status());
  const avant = (await premiere.json()) as PositionFile;
  test.skip(
    avant.statut === "ADMIS",
    "client.test déjà admis (admission de 600 s d'un passage récent) : position non observable",
  );

  // E16 : position et estimation dans une région status, barre de progression libellée.
  await expect(
    page.getByRole("heading", { name: "Vous êtes dans la file d'attente" }),
  ).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: /^Position : \d/ })).toContainText(
    "Attente estimée",
  );
  await expect(
    page.getByRole("progressbar", { name: "Progression dans la file d'attente" }),
  ).toBeVisible();

  // CA1 : rafraîchir ne fait pas perdre sa place (même position ou meilleure, ou admis entre-temps).
  const entreeApres = prochaineEntreeFile(page);
  await page.reload();
  const apres = (await (await entreeApres).json()) as PositionFile;
  if (apres.statut === "EN_ATTENTE") {
    expect(apres.position, "position après rafraîchissement").not.toBeNull();
    expect(apres.position ?? Infinity).toBeLessThanOrEqual(avant.position ?? 0);
  } else {
    expect(apres.statut).toBe("ADMIS");
  }

  // Admission à la vague suivante : redirection vers le plan de salle, réservation possible.
  await expect(page).toHaveURL(new RegExp(`/seances/${SOIREE_JAZZ}$`), { timeout: 30_000 });
  await expect(page.getByText(/^Admission valable jusqu'à/)).toBeVisible();
  await expect(page.getByRole("grid", { name: /^Plan de salle/ })).toBeVisible();
});
