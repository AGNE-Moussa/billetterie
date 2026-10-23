// CA2 (BIL-F26) : l'accueil est servi via Traefik et une URL profonde rechargée tombe sur le
// repli SPA de Nginx (200, index.html), pas sur un 404.
import { expect, test } from "@playwright/test";

test("test_l_accueil_s_affiche_via_traefik_et_une_url_profonde_rechargee_ne_renvoie_pas_404", async ({
  page,
}) => {
  const accueil = await page.goto("/");
  expect(accueil?.status()).toBe(200);
  expect(accueil?.headers()["content-type"]).toContain("text/html");
  await expect(page.getByRole("heading", { level: 1, name: "Billetterie" })).toBeVisible();

  await page.goto("/page-inexistante");
  const rechargee = await page.reload();
  expect(rechargee?.status()).toBe(200);
  expect(rechargee?.headers()["content-type"]).toContain("text/html");
  await expect(page.getByRole("heading", { level: 1, name: "Page introuvable" })).toBeVisible();
});
