// CA2 (BIL-F28) : la mise en page se parcourt entièrement au clavier dans un vrai navigateur,
// contre la plateforme démarrée par `make up` et le vrai Keycloak. Seul le parcours vérifie le
// contour de focus (calculé par le navigateur, absent de jsdom).
import { expect, test, type Locator, type Page } from "@playwright/test";

import { CLIENT_TEST, seConnecterSurKeycloak } from "./utilisateursDeTest";

interface ElementAttendu {
  role: "link" | "button";
  nom: string;
}

const ALLER_AU_CONTENU: ElementAttendu = { role: "link", nom: "Aller au contenu" };
// Liens livrés par l'application (src/navigation.ts) : « Accueil » seul, public.
const ACCUEIL: ElementAttendu = { role: "link", nom: "Accueil" };
const BASCULE_THEME: ElementAttendu = { role: "button", nom: "Thème sombre" };
const SE_DECONNECTER: ElementAttendu = { role: "button", nom: "Se déconnecter" };
const SE_CONNECTER: ElementAttendu = { role: "button", nom: "Se connecter" };

// Ordre visuel du cas composant : évitement, navigation, bascule de thème, connexion, puis le
// contenu (la page d'accueil n'a pas d'élément focalisable) et le pied de page (sans lien).
const ORDRE_CONNECTE = [ALLER_AU_CONTENU, ACCUEIL, BASCULE_THEME, SE_DECONNECTER] as const;
const ORDRE_NON_CONNECTE = [ALLER_AU_CONTENU, ACCUEIL, BASCULE_THEME, SE_CONNECTER] as const;

function localiser(page: Page, element: ElementAttendu): Locator {
  return page.getByRole(element.role, { name: element.nom, exact: true });
}

/** Le focus est sur l'élément attendu et le navigateur lui dessine un contour visible. */
async function verifierFocusVisible(page: Page, element: ElementAttendu): Promise<void> {
  await expect(localiser(page, element), `focus sur « ${element.nom} »`).toBeFocused();
  const style = await page.evaluate(() => {
    const actif = document.activeElement;
    if (actif === null || actif === document.body) return null;
    const calcule = getComputedStyle(actif);
    return {
      outlineStyle: calcule.outlineStyle,
      outlineWidth: calcule.outlineWidth,
      boxShadow: calcule.boxShadow,
    };
  });
  expect(style, `élément focalisé pour « ${element.nom} »`).not.toBeNull();
  const contour =
    style !== null && style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) > 0;
  const ombre = style !== null && style.boxShadow !== "none" && style.boxShadow !== "";
  expect(contour || ombre, `contour de focus visible sur « ${element.nom} »`).toBe(true);
}

test("test_la_mise_en_page_se_parcourt_entierement_au_clavier", async ({ page }) => {
  // Connexion de client.test par l'aide existante, comme dans connexion.spec.ts.
  await page.goto("/");
  const seConnecter = localiser(page, SE_CONNECTER);
  await expect(seConnecter).toBeVisible();
  await seConnecter.click();
  await seConnecterSurKeycloak(page, CLIENT_TEST);
  await expect(page).toHaveURL("http://localhost/");
  await expect(page.getByText(CLIENT_TEST.nom, { exact: true })).toBeVisible();

  // Retour sur l'accueil : focus initial sur le document, session retrouvée auprès de Keycloak.
  await page.goto("/");
  await expect(localiser(page, SE_DECONNECTER)).toBeVisible();

  // Tab : ordre visuel, contour de focus visible sur chaque élément.
  for (const element of ORDRE_CONNECTE) {
    await page.keyboard.press("Tab");
    await verifierFocusVisible(page, element);
  }

  // Maj+Tab : ordre exactement inverse jusqu'au lien d'évitement.
  for (const element of [...ORDRE_CONNECTE].reverse().slice(1)) {
    await page.keyboard.press("Shift+Tab");
    await verifierFocusVisible(page, element);
  }

  // Entrée sur « Aller au contenu » : le focus passe dans le contenu principal.
  await page.keyboard.press("Enter");
  const principal = page.getByRole("main");
  await expect(principal).toHaveCount(1);
  await expect
    .poll(() => principal.evaluate((main) => main.contains(document.activeElement)), {
      message: "focus dans main après « Aller au contenu »",
    })
    .toBe(true);

  // Depuis le contenu, Maj+Tab revient dans l'en-tête : « Se déconnecter » puis la bascule.
  await page.keyboard.press("Shift+Tab");
  await verifierFocusVisible(page, SE_DECONNECTER);
  await page.keyboard.press("Shift+Tab");
  await verifierFocusVisible(page, BASCULE_THEME);

  // Espace sur la bascule : data-theme de <html> change, le focus reste sur la bascule.
  const racine = page.locator("html");
  const themeAvant = await racine.getAttribute("data-theme");
  expect(themeAvant, "data-theme posé sur <html> avant la bascule").not.toBeNull();
  await page.keyboard.press("Space");
  await expect
    .poll(() => racine.getAttribute("data-theme"), { message: "data-theme après Espace" })
    .not.toBe(themeAvant);
  await expect(racine).toHaveAttribute("data-theme", /.+/);
  await verifierFocusVisible(page, BASCULE_THEME);

  // Entrée sur « Se déconnecter » : retour à l'accueil, « Se connecter » atteint au clavier.
  await page.keyboard.press("Tab");
  await verifierFocusVisible(page, SE_DECONNECTER);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("http://localhost/");
  await expect(localiser(page, SE_CONNECTER)).toBeVisible();
  await expect(page.getByText(CLIENT_TEST.nom, { exact: true })).toHaveCount(0);

  for (const element of ORDRE_NON_CONNECTE) {
    await page.keyboard.press("Tab");
    await verifierFocusVisible(page, element);
  }
});
