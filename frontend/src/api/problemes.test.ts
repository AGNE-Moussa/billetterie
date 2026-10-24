// Cas composant de BIL-F27 (E4) : conversion des Problem Details en
// {titre, detail, code, correlationId, erreurs}. Corps conformes au schéma Probleme du contrat
// echo (types générés), en application/problem+json ; API simulée par MSW.
import { http, HttpResponse } from "msw";

import { serveurMsw } from "../mocks/serveur";
import { listerEchos } from "./echos";
import type { Probleme } from "./genere/echo";
import { convertirReponse, ErreurApi } from "./problemes";

const FORMAT_UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

it("test_un_probleme_est_converti_en_titre_detail_code_correlation_et_erreurs", async () => {
  const correlationId = crypto.randomUUID();
  const corps: Probleme = {
    type: "about:blank",
    title: "Not Found",
    status: 404,
    detail: "Aucun echo pour ce message.",
    code: "ECHO_INTROUVABLE",
    correlation_id: correlationId,
  };
  // Réponse de GET /api/v1/echos/{message} (404 du contrat).
  const reponse = new Response(JSON.stringify(corps), {
    status: 404,
    headers: { "Content-Type": "application/problem+json", "X-Correlation-Id": correlationId },
  });

  const probleme = await convertirReponse(reponse).catch((erreur: unknown) => erreur);

  expect(probleme).toMatchObject({
    titre: "Not Found",
    detail: "Aucun echo pour ce message.",
    code: "ECHO_INTROUVABLE",
    correlationId,
  });
  expect(probleme).toHaveProperty("erreurs", []);
});

it("test_l_identifiant_de_correlation_renvoye_par_la_reponse_est_conserve_dans_l_erreur", async () => {
  const correlationReponse = crypto.randomUUID();
  const correlationsEmises: (string | null)[] = [];
  serveurMsw.use(
    http.get("*/api/v1/echos", ({ request }) => {
      correlationsEmises.push(request.headers.get("X-Correlation-Id"));
      return HttpResponse.json<Probleme>(
        {
          type: "about:blank",
          title: "Not Found",
          status: 404,
          detail: "Aucun echo pour ce message.",
          code: "ECHO_INTROUVABLE",
        },
        {
          status: 404,
          headers: {
            "Content-Type": "application/problem+json",
            "X-Correlation-Id": correlationReponse,
          },
        },
      );
    }),
  );

  const erreur = await listerEchos().then(
    () => null,
    (raison: unknown) => raison,
  );

  expect(erreur).toBeInstanceOf(ErreurApi);
  expect(correlationsEmises).toHaveLength(1);
  expect(correlationsEmises[0]).toMatch(FORMAT_UUID_V4);
  expect(correlationsEmises[0]).not.toBe(correlationReponse);
  expect((erreur as ErreurApi).probleme.correlationId).toBe(correlationReponse);
});
