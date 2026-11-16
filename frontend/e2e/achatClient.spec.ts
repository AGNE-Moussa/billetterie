// Parcours client (BIL-019 à BIL-021, BIL-024) contre la plateforme démarrée : catalogue, fiche
// événement, plan de salle d'une séance HORS file (créée par le test), choix d'une place au
// clavier, réservation, paiement, confirmation et billet avec son QR code ; puis carte refusée.
// La séance est créée par admin.test (donneesDeTest.ts) : rejouable sans dépendre des places
// encore libres du jeu de démonstration ni du plafond de 10 billets par séance.
import { expect, test, type Page } from "@playwright/test";

import { attendrePlanDeSalle, creerSeanceDeTest, type SeanceCreee } from "./donneesDeTest";
import { CLIENT_TEST, seConnecterSurKeycloak } from "./utilisateursDeTest";

const CARTE_ACCEPTEE = "4242424242424242";
const CARTE_REFUSEE = "4000000000000002";

test.describe.configure({ mode: "serial" });

let seance: SeanceCreee;

test.beforeAll(async ({ browser }) => {
  test.setTimeout(90_000);
  seance = await creerSeanceDeTest(browser);
});

/** Place du plan par son nom accessible (« Rang A, place 2, catégorie Or, 45,00 €, libre »). */
function place(page: Page, numero: number, etat: "libre" | "sélectionnée" | "indisponible") {
  return page.getByRole("button", {
    name: new RegExp(`^Rang A, place ${String(numero)}, catégorie Or, .*, ${etat}$`),
  });
}

/** Catalogue (recherche du nom unique) → fiche événement → plan de salle de la séance. */
async function ouvrirLePlanDepuisLeCatalogue(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Événements" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Rechercher" }).fill(seance.nomEvenement);
  await page.getByRole("button", { name: "Filtrer" }).click();
  await expect(page).toHaveURL(/[?&]q=/);
  await page.getByRole("link", { name: `Voir les séances de ${seance.nomEvenement}` }).click();

  await expect(page).toHaveURL(`/evenements/${seance.evenementId}`);
  await expect(page.getByRole("heading", { level: 1, name: seance.nomEvenement })).toBeVisible();
  const seances = page.getByRole("list", { name: "Séances de l'événement" });
  await expect(seances.getByText(`${seance.nomLieu}, ${seance.villeLieu}`)).toBeVisible();
  await seances.getByRole("link", { name: /^Choisir la séance du/ }).click();

  await expect(page).toHaveURL(new RegExp(`/seances/${seance.seanceId}$`));
  await attendrePlanDeSalle(page);
}

/** Sélectionne la place `numero` du rang A au clavier : focus dans la grille, flèches, Espace. */
async function choisirAuClavier(page: Page, numero: number): Promise<void> {
  // La grille n'a qu'une place dans l'ordre de tabulation : Tab depuis « Retour à l'événement »
  // finit par l'atteindre ; on y entre par la première place, comme un Tab dans la grille.
  await place(page, 1, "libre").focus();
  for (let i = 1; i < numero; i += 1) {
    await page.keyboard.press("ArrowRight");
  }
  await expect(place(page, numero, "libre")).toBeFocused();
  await page.keyboard.press("Space");
  await expect(place(page, numero, "sélectionnée")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText(new RegExp(`Sélection : A${String(numero)} - `))).toBeVisible();
}

/** « Se connecter pour réserver » : Keycloak, puis retour sur la séance avec la sélection. */
async function seConnecterPourReserver(page: Page, numero: number): Promise<void> {
  await page.getByRole("button", { name: "Se connecter pour réserver" }).click();
  await seConnecterSurKeycloak(page, CLIENT_TEST);
  await expect(page).toHaveURL(new RegExp(`/seances/${seance.seanceId}\\?places=`));
  await expect(page.getByText(CLIENT_TEST.nom, { exact: true })).toBeVisible();
  await expect(place(page, numero, "sélectionnée")).toBeVisible();
}

/** « Réserver cette place » → E04, compte à rebours affiché, montant de 45 euros. */
async function reserver(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Réserver cette place" }).click();
  await expect(page).toHaveURL(/\/commandes\/[0-9a-f-]{36}\/paiement$/);
  await expect(page.getByRole("heading", { level: 1, name: "Paiement" })).toBeVisible();
  await expect(page.getByRole("timer")).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Places de la commande" }).getByText(/Rang A, place \d/),
  ).toBeVisible();
}

async function payer(page: Page, carte: string): Promise<void> {
  await page.getByLabel("Numéro de carte").fill(carte);
  await page.getByRole("button", { name: /^Payer 45,00/ }).click();
}

test("test_un_client_achete_une_place_choisie_au_clavier_et_obtient_son_billet_avec_qr_code", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await ouvrirLePlanDepuisLeCatalogue(page);
  await choisirAuClavier(page, 2);
  await seConnecterPourReserver(page, 2);
  await reserver(page);

  await payer(page, CARTE_ACCEPTEE);

  // Confirmation (E05).
  await expect(page).toHaveURL(/\/commandes\/[0-9a-f-]{36}$/);
  await expect(
    page.getByRole("status").filter({ hasText: "Vos billets arrivent aussi par e-mail." }),
  ).toBeVisible();
  await expect(page.getByText("Confirmée", { exact: true })).toBeVisible();
  // Billet émis en asynchrone (ticketing.order.confirmed) : la page relit les billets.
  const voirBillet = page.getByRole("link", { name: /^Voir le billet Rang A, place 2$/ });
  await expect(voirBillet).toBeVisible({ timeout: 60_000 });
  await voirBillet.click();

  // Billet (E08) avec QR code.
  await expect(page).toHaveURL(/\/billets\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 1, name: seance.nomEvenement })).toBeVisible();
  await expect(page.getByRole("img", { name: "QR code du billet rang a, place 2" })).toBeVisible();

  // Le billet figure dans « Mes billets » (E07).
  await page.getByRole("link", { name: "Mes billets" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Mes billets" })).toBeVisible();
  await expect(
    page
      .getByRole("article", { name: seance.nomEvenement })
      .getByRole("link", { name: "Afficher le QR code du billet Rang A, place 2" }),
  ).toBeVisible();
});

test("test_une_carte_refusee_libere_la_place_et_le_signale_au_client", async ({ page }) => {
  test.setTimeout(120_000);
  await ouvrirLePlanDepuisLeCatalogue(page);
  // La place 2 a été vendue par le parcours précédent : indisponible pour tous.
  await expect(place(page, 2, "indisponible")).toHaveAttribute("aria-disabled", "true");
  await choisirAuClavier(page, 3);
  await seConnecterPourReserver(page, 3);
  await reserver(page);

  await payer(page, CARTE_REFUSEE);

  await expect(page.getByRole("alert").filter({ hasText: "Paiement refusé" })).toContainText(
    "Paiement refusé, vos places sont libérées.",
  );
  await page.getByRole("link", { name: "Retour au plan de salle" }).click();
  await expect(page).toHaveURL(new RegExp(`/seances/${seance.seanceId}$`));
  await attendrePlanDeSalle(page);
  // La place redevient libre (verrou levé après le refus).
  await expect(async () => {
    await page.getByRole("button", { name: "Rafraîchir le plan" }).click();
    await expect(place(page, 3, "libre")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
});
