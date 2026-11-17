// Inscription d'un client (libre-service Keycloak) contre la plateforme démarrée : formulaire
// Ovation, e-mail de confirmation lu dans Mailpit (SMTP de test, http://127.0.0.1:8025), retour
// connecté avec le rôle customer (groupe par défaut « clients ») : « Mes billets » visible,
// espace organisateur absent. Adresse unique en @exemple.test, mot de passe aléatoire.
import { randomBytes } from "node:crypto";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { suffixeUnique } from "./donneesDeTest";

const MAILPIT = "http://127.0.0.1:8025";

/** Lien d'action du dernier e-mail reçu par `adresse` (attendu 30 s au plus). */
async function lienDeConfirmation(api: APIRequestContext, adresse: string): Promise<string> {
  let lien: string | undefined;
  await expect(async () => {
    const recherche = await api.get(`${MAILPIT}/api/v1/search`, {
      params: { query: `to:"${adresse}"` },
    });
    const { messages } = (await recherche.json()) as { messages: { ID: string }[] };
    const premier = messages[0];
    expect(premier, `e-mail de confirmation pour ${adresse}`).toBeDefined();
    const message = await api.get(`${MAILPIT}/api/v1/message/${premier?.ID ?? ""}`);
    const { Text } = (await message.json()) as { Text: string };
    lien = /https?:\/\/\S+action-token\S+/.exec(Text)?.[0];
    expect(lien, "lien d'action dans l'e-mail").toBeDefined();
  }).toPass({ timeout: 30_000 });
  return lien ?? "";
}

async function remplirInscription(page: Page, adresse: string, motDePasse: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "Créer un compte" }).click();
  await expect(page.getByRole("heading", { name: "Créer un compte" })).toBeVisible();
  // Champs par rôle et nom accessible (le « * » des champs obligatoires est aria-hidden).
  const champ = (nom: string) => page.getByRole("textbox", { name: nom, exact: true });
  await champ("Prénom").fill("Camille");
  await champ("Nom").fill("Exemple");
  await champ("Adresse e-mail").fill(adresse);
  await champ("Mot de passe").fill(motDePasse);
  await champ("Confirmer le mot de passe").fill(motDePasse);
  await page.getByRole("button", { name: "Créer mon compte" }).click();
}

test("test_un_visiteur_cree_son_compte_confirme_son_e_mail_et_arrive_connecte", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const adresse = `client.${suffixeUnique()}@exemple.test`;

  await remplirInscription(page, adresse, randomBytes(12).toString("base64url"));

  // verifyEmail : Keycloak attend la confirmation avant de rendre la main au front.
  await expect(page.getByRole("heading", { name: "Confirmez votre adresse e-mail" })).toBeVisible();
  await page.goto(await lienDeConfirmation(request, adresse));

  await expect(page.getByText(adresse, { exact: true })).toBeVisible({ timeout: 30_000 });
  const navigation = page.getByRole("navigation", { name: "Navigation principale" });
  await expect(navigation.getByRole("link", { name: "Mes billets" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Espace organisateur" })).toHaveCount(0);
});

test("test_un_mot_de_passe_trop_court_est_refuse_en_francais", async ({ page }) => {
  await remplirInscription(page, `court.${suffixeUnique()}@exemple.test`, "court");

  await expect(
    page.getByText("Le mot de passe doit contenir au moins 10 caractères."),
  ).toBeVisible();
});
