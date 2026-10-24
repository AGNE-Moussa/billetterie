// Cas composant de BIL-F27 (E4) : le composant <Erreur probleme> annonce l'erreur en alerte
// (titre, détail, erreurs de champ, « Référence : <correlationId> ») et le message générique
// pour toute erreur qui n'est pas un Problem Details. API simulée par MSW (types générés).
import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { listerEchos } from "../api/echos";
import type { Probleme } from "../api/genere/echo";
import { convertirReponse, ErreurApi, type ProblemeAffichable } from "../api/problemes";
import { serveurMsw } from "../mocks/serveur";
import { Erreur } from "./Erreur";

const MESSAGE_GENERIQUE_ATTENDU =
  "Le service est momentanément indisponible. Réessayez dans quelques instants.";

/** Raison du rejet de `listerEchos`, `null` si l'appel réussit. */
async function erreurDeListerEchos(parametres?: Parameters<typeof listerEchos>[0]) {
  return listerEchos(parametres).then(
    () => null,
    (raison: unknown) => raison,
  );
}

it("test_le_composant_d_erreur_annonce_le_titre_le_detail_et_la_reference_en_alerte", () => {
  const correlationId = crypto.randomUUID();
  const probleme: ProblemeAffichable = {
    titre: "Not Found",
    detail: "Aucun echo pour ce message.",
    code: "ECHO_INTROUVABLE",
    correlationId,
    erreurs: [],
  };

  render(<Erreur probleme={probleme} />);

  const alerte = screen.getByRole("alert");
  expect(alerte).toHaveTextContent("Not Found");
  expect(alerte).toHaveTextContent("Aucun echo pour ce message.");
  expect(alerte).toHaveTextContent(`Référence : ${correlationId}`);
  expect(alerte).not.toHaveTextContent(/Error|at \S+ \(/);
});

// Cas composant de BIL-F28 (CA1, état commun « erreur ») : sans identifiant de corrélation,
// aucune référence n'est affichée.
it("test_l_etat_erreur_sans_identifiant_de_correlation_n_affiche_pas_de_reference", () => {
  const probleme: ProblemeAffichable = {
    titre: "Erreur de test",
    detail: "Détail de l'erreur de test.",
    code: "ERREUR_DE_TEST",
    correlationId: null,
    erreurs: [],
  };

  render(<Erreur probleme={probleme} />);

  const alerte = screen.getByRole("alert");
  expect(alerte).toHaveTextContent("Erreur de test");
  expect(alerte).toHaveTextContent("Détail de l'erreur de test.");
  expect(alerte).not.toHaveTextContent("Référence");
});

it("test_le_composant_d_erreur_liste_les_erreurs_d_une_requete_invalide", async () => {
  serveurMsw.use(
    http.get("*/api/v1/echos", () =>
      HttpResponse.json<Probleme>(
        {
          type: "about:blank",
          title: "Unprocessable Entity",
          status: 422,
          detail: "La requête est invalide.",
          code: "REQUETE_INVALIDE",
          correlation_id: crypto.randomUUID(),
          erreurs: [{ champ: "query.page", message: "doit être supérieur ou égal à 1" }],
        },
        { status: 422, headers: { "Content-Type": "application/problem+json" } },
      ),
    ),
  );

  const erreur = await erreurDeListerEchos({ page: 0 });

  expect(erreur).toBeInstanceOf(ErreurApi);
  expect((erreur as ErreurApi).probleme.erreurs).toEqual([
    { champ: "query.page", message: "doit être supérieur ou égal à 1" },
  ]);
  render(<Erreur probleme={erreur} />);
  const liste = within(screen.getByRole("alert")).getByRole("list");
  const elements = within(liste).getAllByRole("listitem");
  expect(elements).toHaveLength(1);
  expect(elements[0]).toHaveTextContent("query.page");
  expect(elements[0]).toHaveTextContent("doit être supérieur ou égal à 1");
});

it.each([
  {
    status: 401,
    code: "JETON_EXPIRE",
    title: "Unauthorized",
    detail: "Le jeton de test a expiré.",
  },
  {
    status: 403,
    code: "SCOPE_MANQUANT",
    title: "Forbidden",
    detail: "Le scope de test echos:read est absent du jeton.",
  },
  {
    status: 403,
    code: "ROLE_MANQUANT",
    title: "Forbidden",
    detail: "Le rôle de test requis est absent du jeton.",
  },
])(
  "test_le_message_affiche_est_celui_du_serveur_quel_que_soit_le_code ($status $code)",
  async ({ status, code, title, detail }) => {
    const corps: Probleme = { type: "about:blank", title, status, detail, code };
    const reponse = new Response(JSON.stringify(corps), {
      status,
      headers: { "Content-Type": "application/problem+json" },
    });
    const probleme = await convertirReponse(reponse).catch((raison: unknown) => raison);

    render(<Erreur probleme={probleme} />);

    const alerte = screen.getByRole("alert");
    expect(alerte).toHaveTextContent(title);
    expect(alerte).toHaveTextContent(detail);
    const reste = (alerte.textContent ?? "").replace(title, "").replace(detail, "").trim();
    expect(reste).toBe("");
  },
);

it.each([
  {
    cas: "502 text/html de Traefik",
    reponse: () =>
      HttpResponse.html("<html><body><h1>502 Bad Gateway</h1></body></html>", { status: 502 }),
  },
  { cas: "500 au corps vide", reponse: () => new HttpResponse(null, { status: 500 }) },
  { cas: "429 au corps vide", reponse: () => new HttpResponse(null, { status: 429 }) },
])(
  "test_une_erreur_qui_n_est_pas_un_probleme_donne_le_message_generique ($cas)",
  async ({ reponse }) => {
    serveurMsw.use(http.get("*/api/v1/echos", reponse));

    const erreur = await erreurDeListerEchos();
    render(<Erreur probleme={erreur} />);

    const alerte = screen.getByRole("alert");
    expect(alerte).toHaveTextContent(MESSAGE_GENERIQUE_ATTENDU);
    expect(alerte).not.toHaveTextContent(/JSON|SyntaxError|Bad Gateway/);
  },
);

it("test_une_panne_reseau_donne_le_message_generique", async () => {
  serveurMsw.use(http.get("*/api/v1/echos", () => HttpResponse.error()));

  const erreur = await erreurDeListerEchos();
  render(<Erreur probleme={erreur} />);

  expect(screen.getByRole("alert")).toHaveTextContent(MESSAGE_GENERIQUE_ATTENDU);
});
