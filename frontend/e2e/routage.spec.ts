// E5 (BIL-F26) : le routeur du front (/) a une priorité plus basse que /api et /auth.
import { expect, test } from "@playwright/test";

test("test_api_et_auth_restent_servis_par_leurs_services_et_non_par_le_front", async ({
  request,
}) => {
  const api = await request.get("/api/v1/echos");
  expect(api.status()).toBe(401);
  expect(api.headers()["content-type"]).toContain("application/problem+json");

  const auth = await request.get("/auth/realms/billetterie/.well-known/openid-configuration");
  expect(auth.status()).toBe(200);
  expect(auth.headers()["content-type"]).toContain("application/json");
  const configuration = (await auth.json()) as { issuer?: string };
  expect(configuration.issuer).toBe("http://localhost/auth/realms/billetterie");
});
