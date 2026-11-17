// Données créées par les parcours eux-mêmes, par l'interface de l'organisateur (admin.test) :
// un lieu, un événement et une séance à noms uniques, pour que chaque exécution parte d'une
// séance vierge (plafond de 10 billets par client et par séance, places déjà vendues).
// Seule la séance « Soirée jazz » du jeu de démonstration est sous file d'attente
// (SEANCES_SOUS_FILE est une liste fixe) : les séances créées ici ne le sont jamais.
import { expect, type Browser, type Page } from "@playwright/test";

import { ADMIN_TEST, seConnecterSurKeycloak } from "./utilisateursDeTest";

export interface SeanceCreee {
  nomLieu: string;
  villeLieu: string;
  nomEvenement: string;
  evenementId: string;
  seanceId: string;
}

/** Suffixe unique d'une exécution (horodatage et hasard), lisible dans les noms. */
export function suffixeUnique(): string {
  return `${String(Date.now())}-${String(Math.floor(Math.random() * 1000))}`;
}

/** Valeur d'un champ datetime-local (heure locale), `jours` jours après maintenant à 20 h. */
function dateLocaleDansJours(jours: number): string {
  const date = new Date(Date.now() + jours * 24 * 3600 * 1000);
  const deux = (n: number) => String(n).padStart(2, "0");
  return `${String(date.getFullYear())}-${deux(date.getMonth() + 1)}-${deux(date.getDate())}T20:00`;
}

/** Ouvre une route protégée `admin` : la garde envoie vers Keycloak, puis ramène sur la route. */
export async function ouvrirCommeAdmin(page: Page, chemin: string): Promise<void> {
  await page.goto(chemin);
  await seConnecterSurKeycloak(page, ADMIN_TEST);
  await expect(page).toHaveURL(new RegExp(`${chemin}$`));
}

/** E15 : crée un lieu par le formulaire « Nouveau lieu » (page déjà ouverte sur E15). */
export async function creerLieu(page: Page, nom: string, ville: string): Promise<void> {
  await expect(page.getByRole("heading", { level: 1, name: "Lieux" })).toBeVisible();
  const formulaire = page.getByRole("region", { name: "Nouveau lieu" });
  await formulaire.getByLabel("Nom").fill(nom);
  await formulaire.getByLabel("Adresse").fill("1 rue des Tests");
  await formulaire.getByLabel("Ville").fill(ville);
  await formulaire.getByRole("button", { name: "Créer le lieu" }).click();
  await expect(page.getByText(`Lieu « ${nom} » créé.`)).toBeVisible();
}

/** E11 : crée un événement ; renvoie son identifiant (lu dans l'URL de E12). */
export async function creerEvenement(page: Page, nom: string): Promise<string> {
  await page.goto("/organisateur");
  await page.getByRole("link", { name: "Créer un événement" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Nouvel événement" })).toBeVisible();
  await page.getByLabel("Nom").fill(nom);
  await page.getByLabel("Description").fill("Événement créé par un parcours Playwright.");
  await page.getByRole("button", { name: "Créer", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: nom })).toBeVisible();
  const correspondance = /\/organisateur\/evenements\/([0-9a-f-]{36})$/.exec(page.url());
  expect(correspondance, "identifiant de l'événement dans l'URL de E12").not.toBeNull();
  return correspondance?.[1] ?? "";
}

/**
 * E13 : programme une séance (une catégorie « Or » à 45 euros, rang A de 6 places) dans le lieu
 * donné ; renvoie son identifiant (lien « Voir » de E12).
 */
export async function programmerSeance(page: Page, libelleLieu: string): Promise<string> {
  await page.getByRole("link", { name: "Programmer une séance" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Nouvelle séance" })).toBeVisible();
  await page.getByLabel("Lieu").selectOption({ label: libelleLieu });
  await page.getByLabel("Début").fill(dateLocaleDansJours(30));
  const categorie = page.getByRole("group", { name: "Catégorie 1" });
  await categorie.getByLabel("Nom").fill("Or");
  await categorie.getByLabel("Prix en euros").fill("45");
  await categorie.getByLabel(/^Rang 1\b/).fill("A");
  await categorie.getByLabel("Places du rang 1").fill("6");
  await page.getByRole("button", { name: "Programmer", exact: true }).click();
  await expect(
    page.getByText("Séance programmée : ses places sont en cours de création."),
  ).toBeVisible();
  const lienSeance = page
    .getByRole("table", { name: "Séances de l'événement" })
    .getByRole("link", { name: /^Voir la séance du/ });
  await expect(lienSeance).toHaveCount(1);
  const href = (await lienSeance.getAttribute("href")) ?? "";
  const correspondance = /\/organisateur\/seances\/([0-9a-f-]{36})$/.exec(href);
  expect(correspondance, "identifiant de la séance dans le lien « Voir »").not.toBeNull();
  return correspondance?.[1] ?? "";
}

/** Lieu, événement et séance créés par admin.test dans un contexte de navigateur séparé. */
export async function creerSeanceDeTest(browser: Browser): Promise<SeanceCreee> {
  const suffixe = suffixeUnique();
  const nomLieu = `Salle E2E ${suffixe}`;
  const villeLieu = "Testville";
  const nomEvenement = `Concert E2E ${suffixe}`;
  const contexte = await browser.newContext();
  const page = await contexte.newPage();
  try {
    await ouvrirCommeAdmin(page, "/organisateur/lieux");
    await creerLieu(page, nomLieu, villeLieu);
    const evenementId = await creerEvenement(page, nomEvenement);
    const seanceId = await programmerSeance(page, `${nomLieu}, ${villeLieu}`);
    return { nomLieu, villeLieu, nomEvenement, evenementId, seanceId };
  } finally {
    await contexte.close();
  }
}

/** Plan de salle (E03) : attend que Billets ait créé les places (création asynchrone). */
export async function attendrePlanDeSalle(page: Page): Promise<void> {
  const grille = page.getByRole("grid", { name: /^Plan de salle/ });
  await expect(async () => {
    if (!(await grille.isVisible())) {
      const rafraichir = page.getByRole("button", { name: "Rafraîchir", exact: true });
      if (await rafraichir.isVisible()) await rafraichir.click();
    }
    await expect(grille).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
}
