// CA2 de BIL-019 : le catalogue reste utilisable sur un écran de téléphone (360 x 740), contre
// la plateforme démarrée et le jeu de démonstration (make demo) : rien ne déborde à
// l'horizontale, les filtres se remplissent et s'appliquent, une fiche s'ouvre au toucher.
import { expect, test, type Page } from "@playwright/test";

test.use({ viewport: { width: 360, height: 740 }, hasTouch: true, isMobile: true });

async function sansDefilementHorizontal(page: Page): Promise<void> {
  const largeurs = await page.evaluate(() => ({
    contenu: document.documentElement.scrollWidth,
    ecran: window.innerWidth,
  }));
  expect(largeurs.contenu, "largeur du contenu face à l'écran").toBeLessThanOrEqual(largeurs.ecran);
}

test("test_le_catalogue_reste_utilisable_sur_un_ecran_de_telephone", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Événements" })).toBeVisible();
  const premiereFiche = page.getByRole("link", { name: /^Voir les séances de / }).first();
  await expect(premiereFiche).toBeVisible();
  await sansDefilementHorizontal(page);

  // En-tête utilisable : navigation et connexion visibles.
  await expect(page.getByRole("link", { name: "Événements", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Se connecter" })).toBeVisible();

  // Filtres : saisie et application, reflétées dans l'URL.
  const recherche = page.getByRole("searchbox", { name: "Rechercher" });
  await recherche.tap();
  await recherche.fill("zzz-aucun-evenement-e2e");
  await page.getByRole("button", { name: "Filtrer" }).tap();
  await expect(page).toHaveURL(/[?&]q=zzz-aucun-evenement-e2e/);
  await expect(page.getByText("Aucun événement ne correspond à ces filtres.")).toBeVisible();
  await sansDefilementHorizontal(page);
  await page.getByRole("button", { name: "Effacer les filtres" }).first().tap();
  await expect(page).not.toHaveURL(/[?&]q=/);

  // Une fiche s'ouvre au toucher et reste lisible sans défilement horizontal.
  const nom = ((await premiereFiche.textContent()) ?? "").replace(/^Voir les séances de /, "");
  await premiereFiche.tap();
  await expect(page).toHaveURL(/\/evenements\/[0-9a-f-]{36}/);
  await expect(page.getByRole("heading", { level: 1, name: nom })).toBeVisible();
  await sansDefilementHorizontal(page);
});
