// Cas composant de BIL-F28 (CA1, carte) : <article> nommé par son titre, titre h2 par défaut et
// niveau réglable, actions rendues sans rendre la carte entière cliquable.
import { render, screen, within } from "@testing-library/react";

import { Bouton } from "./Bouton";
import { Carte } from "./Carte";

it("test_la_carte_est_un_article_nomme_par_son_titre_avec_son_contenu", () => {
  render(
    <Carte titre="Carte de test">
      <p>Contenu de test</p>
    </Carte>,
  );

  const article = screen.getByRole("article", { name: "Carte de test" });
  expect(within(article).getByRole("heading", { level: 2, name: "Carte de test" })).toBeVisible();
  expect(within(article).getByText("Contenu de test")).toBeInTheDocument();
});

it("test_le_niveau_du_titre_de_la_carte_est_reglable", () => {
  render(
    <Carte titre="Carte de test" niveauTitre={3}>
      <p>Contenu de test</p>
    </Carte>,
  );

  const article = screen.getByRole("article", { name: "Carte de test" });
  expect(within(article).getByRole("heading", { level: 3, name: "Carte de test" })).toBeVisible();
  expect(within(article).queryByRole("heading", { level: 2 })).not.toBeInTheDocument();
});

it("test_la_carte_rend_ses_actions", () => {
  render(
    <Carte titre="Carte de test" actions={<Bouton>Action de test</Bouton>}>
      <p>Contenu de test</p>
    </Carte>,
  );

  const article = screen.getByRole("article", { name: "Carte de test" });
  expect(within(article).getByRole("button", { name: "Action de test" })).toBeInTheDocument();
  expect(article.tagName).toBe("ARTICLE");
  expect(within(article).getAllByRole("button")).toHaveLength(1);
  expect(within(article).queryByRole("link")).not.toBeInTheDocument();
  expect(article.closest("button, a")).toBeNull();
});
