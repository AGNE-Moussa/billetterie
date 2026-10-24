// CA2 (BIL-F27) : après une vraie connexion, aucun des jetons renvoyés par Keycloak n'est dans
// localStorage, sessionStorage ni document.cookie. Les jetons ne sont jamais affichés.
import { expect, test } from "@playwright/test";

import { CLIENT_TEST, seConnecterSurKeycloak } from "./utilisateursDeTest";

const POINT_DE_JETON = "/auth/realms/billetterie/protocol/openid-connect/token";

interface ReponseJeton {
  access_token?: string;
  refresh_token?: string;
  id_token?: string;
}

test("test_apres_une_vraie_connexion_aucun_jeton_n_est_dans_le_stockage_du_navigateur", async ({
  page,
}) => {
  await page.goto("/");
  const seConnecter = page.getByRole("button", { name: "Se connecter" });
  await expect(seConnecter).toBeVisible();
  await seConnecter.click();

  const reponseJeton = page.waitForResponse(
    (reponse) => new URL(reponse.url()).pathname === POINT_DE_JETON && reponse.ok(),
  );
  await seConnecterSurKeycloak(page, CLIENT_TEST);
  const corps = (await (await reponseJeton).json()) as ReponseJeton;

  await expect(page).toHaveURL("http://localhost/");
  await expect(page.getByText(CLIENT_TEST.nom, { exact: true })).toBeVisible();

  const jetons = [corps.access_token, corps.refresh_token, corps.id_token].filter(
    (jeton): jeton is string => typeof jeton === "string" && jeton !== "",
  );
  expect(jetons.length, "la réponse du point de jeton porte des jetons").toBeGreaterThan(0);

  const stockage = await page.evaluate(() => {
    const valeurs = (zone: Storage) =>
      Array.from({ length: zone.length }, (_, i) => zone.getItem(zone.key(i) ?? "") ?? "");
    return {
      localStorage: valeurs(window.localStorage),
      sessionStorage: valeurs(window.sessionStorage),
      cookie: [document.cookie],
    };
  });

  for (const [zone, valeurs] of Object.entries(stockage)) {
    const fuites = jetons.filter((jeton) => valeurs.some((valeur) => valeur.includes(jeton)));
    // Message sans le jeton : seul le nombre de jetons trouvés est rapporté.
    expect(fuites.length, `jetons trouvés dans ${zone}`).toBe(0);
  }
});
