// Cas unitaire de BIL-F27 (décision après la seconde review) : la page de retour après
// connexion reste toujours dans l'application. cheminInterne résout le chemin contre
// l'origine ; toute sortie de l'origine, URL absolue ou page de rappel donne l'accueil.
import { cheminInterne } from "./FournisseurAuthentification";

it.each([
  ["/.//evil.example", "/"],
  ["/%2e//evil.example", "/"],
  ["/x/..//evil.example", "/"],
  ["//evil.example", "/"],
  ["/\\evil.example", "/"],
  ["/\t/evil.example", "/"],
  ["https://evil.example/", "/"],
  ["/espace?x=1#a", "/espace?x=1#a"],
  ["/connexion/rappel", "/"],
])("test_le_chemin_de_retour_reste_toujours_dans_l_application (%j)", (chemin, attendu) => {
  const retour = cheminInterne(chemin);

  expect(retour).toBe(attendu);
  // Assertion générale : chemin relatif à l'origine, jamais une URL relative au protocole.
  expect(retour.startsWith("/")).toBe(true);
  expect(retour.startsWith("//")).toBe(false);
});
