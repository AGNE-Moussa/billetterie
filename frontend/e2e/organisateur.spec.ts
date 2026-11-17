// Parcours organisateur (BIL-022, BIL-024) contre la plateforme démarrée : admin.test crée un
// lieu, un événement et une séance ; la séance apparaît côté client ; il l'annule après une
// confirmation explicite ; un client n'atteint jamais l'espace organisateur (CA1 de BIL-022).
import { expect, test } from "@playwright/test";

import {
  creerEvenement,
  creerLieu,
  ouvrirCommeAdmin,
  programmerSeance,
  suffixeUnique,
} from "./donneesDeTest";
import { CLIENT_TEST, seConnecterSurKeycloak } from "./utilisateursDeTest";

test("test_l_organisateur_cree_lieu_evenement_et_seance_visible_cote_client_puis_l_annule", async ({
  page,
  browser,
}) => {
  test.setTimeout(150_000);
  const suffixe = suffixeUnique();
  const nomLieu = `Salle E2E ${suffixe}`;
  const nomEvenement = `Théâtre E2E ${suffixe}`;

  // Espace organisateur : lien de navigation visible pour admin.test.
  await ouvrirCommeAdmin(page, "/organisateur/lieux");
  await expect(
    page
      .getByRole("navigation", { name: "Navigation principale" })
      .getByRole("link", { name: "Espace organisateur" }),
  ).toBeVisible();
  await creerLieu(page, nomLieu, "Testville");
  // Le nouveau lieu est proposé dans la liste déroulante de E13 (vérifié par programmerSeance).
  const evenementId = await creerEvenement(page, nomEvenement);
  const seanceId = await programmerSeance(page, `${nomLieu}, Testville`);

  // Côté client (visiteur, autre contexte) : la séance figure sur la fiche, réservable.
  const visiteur = await browser.newContext();
  const pageVisiteur = await visiteur.newPage();
  await pageVisiteur.goto(`/evenements/${evenementId}`);
  await expect(pageVisiteur.getByRole("heading", { level: 1, name: nomEvenement })).toBeVisible();
  const seances = pageVisiteur.getByRole("list", { name: "Séances de l'événement" });
  await expect(seances.getByText(`${nomLieu}, Testville`)).toBeVisible();
  await expect(seances.getByRole("link", { name: /^Choisir la séance du/ })).toHaveAttribute(
    "href",
    `/seances/${seanceId}`,
  );

  // E14 : « Annuler la séance » demande confirmation ; « Garder la séance » ne change rien.
  await page
    .getByRole("table", { name: "Séances de l'événement" })
    .getByRole("link", { name: /^Voir la séance du/ })
    .click();
  await expect(page).toHaveURL(`/organisateur/seances/${seanceId}`);
  await expect(page.getByRole("heading", { level: 1, name: /^Séance du / })).toBeVisible();
  const annuler = page.getByRole("button", { name: "Annuler la séance" });
  await annuler.click();
  const dialogue = page.getByRole("dialog", { name: /^Annuler la séance du .* \?$/ });
  await expect(dialogue).toBeVisible();
  await expect(dialogue).toContainText("Tous les acheteurs seront remboursés");
  await dialogue.getByRole("button", { name: "Garder la séance" }).click();
  await expect(dialogue).toBeHidden();
  await expect(annuler).toBeVisible();

  await annuler.click();
  await dialogue.getByRole("button", { name: "Confirmer l'annulation" }).click();
  await expect(page.getByText("Séance annulée, remboursements en cours.")).toBeVisible();
  await expect(page.getByText("Séance annulée.", { exact: true })).toBeVisible();
  await expect(annuler).toHaveCount(0);

  // Côté client : la séance porte « Annulée », plus de lien « Choisir » (cache relu au besoin).
  await expect(async () => {
    await pageVisiteur.reload();
    await expect(seances.getByText("Annulée", { exact: true })).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 60_000 });
  await expect(seances.getByRole("link", { name: /^Choisir la séance du/ })).toHaveCount(0);
  await visiteur.close();
});

test("test_un_client_ne_voit_pas_l_espace_organisateur", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await seConnecterSurKeycloak(page, CLIENT_TEST);
  await expect(page.getByText(CLIENT_TEST.nom, { exact: true })).toBeVisible();

  const navigation = page.getByRole("navigation", { name: "Navigation principale" });
  await expect(navigation.getByRole("link", { name: "Mes billets" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Espace organisateur" })).toHaveCount(0);

  for (const chemin of [
    "/organisateur",
    "/organisateur/lieux",
    "/organisateur/evenements/nouveau",
  ]) {
    await page.goto(chemin);
    await expect(page.getByRole("heading", { level: 1, name: "Accès refusé" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Espace organisateur" })).toHaveCount(0);
  }
});
