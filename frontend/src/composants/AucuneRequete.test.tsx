// Cas composant de BIL-F28 (contrainte) : aucun composant de base n'émet de requête. Chaque
// composant est rendu puis manipulé ; le serveur MSW écoute `request:start` (en plus de
// `onUnhandledFrame: "error"` de setupTests.ts). Chaque rendu vérifie que le composant affiche
// bien quelque chose : sans cela, un composant qui ne rend rien passerait le test.
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef } from "react";
import { MemoryRouter } from "react-router";

import type { ProblemeAffichable } from "../api/problemes";
import { ContexteSession, SESSION_NON_CONNECTEE } from "../auth/session";
import { serveurMsw } from "../mocks/serveur";
import { FournisseurNotifications } from "../notifications/FournisseurNotifications";
import { useNotifications, type Notification } from "../notifications/notifications";
import { FournisseurTheme } from "../theme/FournisseurTheme";
import { BasculeTheme } from "./BasculeTheme";
import { Bouton } from "./Bouton";
import { Carte } from "./Carte";
import { ChampFormulaire } from "./ChampFormulaire";
import { Chargement } from "./Chargement";
import { DialogueConfirmation } from "./DialogueConfirmation";
import { Erreur } from "./Erreur";
import { MiseEnPage } from "./MiseEnPage";
import { TableauPagine } from "./TableauPagine";
import { Vide } from "./Vide";

// Bouchon minimal de HTMLDialogElement.showModal / close (absents de jsdom) ; le bouchon complet
// et son explication sont dans DialogueConfirmation.test.tsx. Sans effet si showModal existe.
if (typeof HTMLDialogElement.prototype.showModal !== "function") {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
    this.querySelector<HTMLElement>("button:not([disabled])")?.focus();
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (this.open) {
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    }
  };
}

function simulerPreferenceClaire() {
  const matchMedia = (requete: string) =>
    ({
      media: requete,
      matches: requete.includes("prefers-color-scheme: light"),
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => true,
    }) as unknown as MediaQueryList;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: matchMedia,
  });
}

function EmetteurDeTest({ notification }: { notification: Notification }) {
  const { notifier } = useNotifications();
  const emise = useRef(false);
  useEffect(() => {
    if (!emise.current) {
      emise.current = true;
      notifier(notification);
    }
  }, [notifier, notification]);
  return null;
}

afterEach(() => {
  serveurMsw.events.removeAllListeners();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  Reflect.deleteProperty(window, "matchMedia");
});

it("test_aucun_composant_de_base_n_emet_de_requete", async () => {
  const user = userEvent.setup();
  const requetes: string[] = [];
  serveurMsw.events.on("request:start", ({ request }) => {
    requetes.push(`${request.method} ${request.url}`);
  });
  simulerPreferenceClaire();

  const miseEnPage = render(
    <FournisseurTheme>
      <FournisseurNotifications>
        <ContexteSession.Provider value={SESSION_NON_CONNECTEE}>
          <MemoryRouter>
            <MiseEnPage>
              <h1>Contenu de test</h1>
            </MiseEnPage>
          </MemoryRouter>
        </ContexteSession.Provider>
      </FournisseurNotifications>
    </FournisseurTheme>,
  );
  expect(screen.getByRole("main")).toHaveTextContent("Contenu de test");
  miseEnPage.unmount();

  const surClic = vi.fn();
  const bouton = render(<Bouton surClic={surClic}>Valider le test</Bouton>);
  await user.click(screen.getByRole("button", { name: "Valider le test" }));
  expect(surClic).toHaveBeenCalledTimes(1);
  bouton.unmount();

  const surChanger = vi.fn();
  const champ = render(
    <ChampFormulaire type="email" libelle="Adresse e-mail" valeur="" surChanger={surChanger} />,
  );
  await user.type(screen.getByLabelText("Adresse e-mail"), "c");
  expect(surChanger).toHaveBeenCalledWith("c");
  champ.unmount();

  const surChangerPage = vi.fn();
  const tableau = render(
    <TableauPagine
      libelle="Éléments de test"
      colonnes={[
        { entete: "Libellé", rendu: (ligne: { id: string; libelle: string }) => ligne.libelle },
      ]}
      page={{
        elements: [{ id: crypto.randomUUID(), libelle: "Élément de test 1" }],
        page: 2,
        size: 20,
        total: 45,
      }}
      cleLigne={(ligne) => ligne.id}
      surChangerPage={surChangerPage}
      messageVide="Aucun élément de test"
    />,
  );
  expect(screen.getByRole("table", { name: "Éléments de test" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Page suivante" }));
  await user.click(screen.getByRole("button", { name: "Page précédente" }));
  expect(surChangerPage).toHaveBeenCalledTimes(2);
  tableau.unmount();

  const carte = render(
    <Carte titre="Carte de test">
      <p>Contenu de test</p>
    </Carte>,
  );
  expect(screen.getByRole("article", { name: "Carte de test" })).toBeInTheDocument();
  carte.unmount();

  const surConfirmer = vi.fn();
  const dialogue = render(
    <DialogueConfirmation
      ouvert
      titre="Confirmer l'action de test"
      message="Cette action de test est définitive."
      surConfirmer={surConfirmer}
      surAnnuler={() => {}}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Confirmer" }));
  expect(surConfirmer).toHaveBeenCalledTimes(1);
  dialogue.unmount();

  const notification = render(
    <FournisseurNotifications>
      <EmetteurDeTest notification={{ type: "succes", message: "Opération de test réussie" }} />
    </FournisseurNotifications>,
  );
  expect(screen.getByText("Opération de test réussie")).toBeInTheDocument();
  notification.unmount();

  const chargement = render(<Chargement />);
  expect(screen.getByRole("status")).toHaveTextContent("Chargement…");
  chargement.unmount();

  const vide = render(<Vide message="Aucun élément de test" />);
  expect(screen.getByText("Aucun élément de test")).toBeInTheDocument();
  vide.unmount();

  const probleme: ProblemeAffichable = {
    titre: "Erreur de test",
    detail: "Détail de l'erreur de test.",
    code: "ERREUR_DE_TEST",
    correlationId: crypto.randomUUID(),
    erreurs: [],
  };
  const erreur = render(<Erreur probleme={probleme} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Erreur de test");
  erreur.unmount();

  const bascule = render(
    <FournisseurTheme>
      <BasculeTheme />
    </FournisseurTheme>,
  );
  await user.click(screen.getByRole("button", { name: "Thème sombre" }));
  bascule.unmount();

  // Laisse passer une éventuelle requête différée avant de conclure.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(requetes).toEqual([]);
});
