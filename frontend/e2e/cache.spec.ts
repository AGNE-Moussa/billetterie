// E4 (BIL-F26) : les fichiers versionnés de /assets ont un cache long, index.html n'en a pas.
import { expect, test } from "@playwright/test";

test("test_les_fichiers_versionnes_ont_un_cache_long_et_l_accueil_non", async ({ request }) => {
  const accueil = await request.get("/");
  expect(accueil.status()).toBe(200);
  expect(accueil.headers()["cache-control"]).toBe("no-cache");

  const html = await accueil.text();
  const script = /<script[^>]*\ssrc="(\/assets\/[^"]+\.js)"/.exec(html);
  expect(script, "un script /assets/*.js est référencé par index.html").not.toBeNull();

  const fichier = await request.get(script?.[1] ?? "");
  expect(fichier.status()).toBe(200);
  expect(fichier.headers()["cache-control"]).toBe("public, max-age=31536000, immutable");
});
