// CA1 (BIL-F27) : chaque utilisateur de test du realm se connecte puis se déconnecte depuis
// l'accueil, contre la plateforme démarrée par `make up` et le vrai Keycloak.
import { expect, test } from "@playwright/test";

import { UTILISATEURS_DE_TEST, seConnecterSurKeycloak } from "./utilisateursDeTest";

for (const utilisateur of UTILISATEURS_DE_TEST) {
  test(`test_chaque_utilisateur_de_test_se_connecte_puis_se_deconnecte_depuis_l_accueil[${utilisateur.nom}]`, async ({
    page,
  }) => {
    await page.goto("/");
    const seConnecterAccueil = page.getByRole("button", { name: "Se connecter" });
    await expect(seConnecterAccueil).toBeVisible();
    await seConnecterAccueil.click();

    await seConnecterSurKeycloak(page, utilisateur);

    await expect(page).toHaveURL("http://localhost/");
    await expect(page.getByText(utilisateur.nom, { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Se déconnecter" }).click();

    await expect(page).toHaveURL("http://localhost/");
    const seConnecter = page.getByRole("button", { name: "Se connecter" });
    await expect(seConnecter).toBeVisible();
    await expect(page.getByText(utilisateur.nom, { exact: true })).toHaveCount(0);

    // Session Keycloak fermée : un nouveau clic réaffiche le formulaire au lieu de reconnecter.
    await seConnecter.click();
    await expect(page.getByLabel("Username or email")).toBeVisible();
  });
}
