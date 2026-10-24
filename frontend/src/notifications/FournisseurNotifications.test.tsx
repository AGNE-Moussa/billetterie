// Cas composant de BIL-F28 (CA1, notification) : `succes` / `info` en role="status", `erreur` en
// role="alert", « Fermer la notification », fermeture automatique après 5 s (jamais pour une
// erreur) suspendue au survol et au focus, aucune prise de focus, empilement dans l'ordre.
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";

import { FournisseurNotifications } from "./FournisseurNotifications";
import { DUREE_NOTIFICATION_MS, useNotifications, type Notification } from "./notifications";

let notifierCapture: ((notification: Notification) => void) | null = null;

/** Retient l'émetteur fourni par le fournisseur pour que le test l'appelle. */
function Emetteur() {
  const { notifier: emettre } = useNotifications();
  useEffect(() => {
    notifierCapture = emettre;
  }, [emettre]);
  return <button type="button">Bouton de test</button>;
}

function rendreFournisseur() {
  return render(
    <FournisseurNotifications>
      <Emetteur />
    </FournisseurNotifications>,
  );
}

function notifier(notification: Notification) {
  act(() => {
    notifierCapture?.(notification);
  });
}

function avancer(millisecondes: number) {
  act(() => {
    vi.advanceTimersByTime(millisecondes);
  });
}

/** Région du rôle donné qui contient le message, `undefined` si aucune. */
function regionContenant(role: "status" | "alert", message: string) {
  return screen.queryAllByRole(role).find((region) => (region.textContent ?? "").includes(message));
}

afterEach(() => {
  notifierCapture = null;
  vi.useRealTimers();
});

it("test_les_regions_d_annonce_sont_presentes_et_vides_avant_toute_notification", () => {
  rendreFournisseur();

  // Décision (validation 2) : deux régions live permanentes, rendues dès le montage.
  const statut = screen.queryByRole("status");
  const alerte = screen.queryByRole("alert");
  expect(statut).not.toBeNull();
  expect(alerte).not.toBeNull();
  expect(statut).toBeEmptyDOMElement();
  expect(alerte).toBeEmptyDOMElement();

  notifier({ type: "succes", message: "Opération de test réussie" });
  notifier({ type: "erreur", message: "Échec de test" });

  // Les messages s'insèrent dans ces mêmes régions, déjà présentes.
  expect(statut).toHaveTextContent("Opération de test réussie");
  expect(statut).not.toHaveTextContent("Échec de test");
  expect(alerte).toHaveTextContent("Échec de test");
  expect(alerte).not.toHaveTextContent("Opération de test réussie");
});

it("test_les_regions_partagees_n_annoncent_que_la_notification_ajoutee", () => {
  rendreFournisseur();

  // Décision (seconde review, S1) : role="status" et role="alert" sont implicitement atomiques ;
  // partagées par toutes les notifications d'un type, elles doivent porter aria-atomic="false"
  // pour qu'un ajout ne fasse pas relire toute la pile.
  const statut = screen.getByRole("status");
  const alerte = screen.getByRole("alert");
  expect(statut).toHaveAttribute("aria-atomic", "false");
  expect(alerte).toHaveAttribute("aria-atomic", "false");

  notifier({ type: "succes", message: "Opération de test réussie" });
  notifier({ type: "erreur", message: "Échec de test" });

  // L'attribut reste posé une fois les régions remplies.
  expect(statut).toHaveAttribute("aria-atomic", "false");
  expect(alerte).toHaveAttribute("aria-atomic", "false");
});

it("test_une_notification_de_succes_est_annoncee_dans_une_region_de_statut", () => {
  rendreFournisseur();

  notifier({ type: "succes", message: "Opération de test réussie" });

  expect(screen.getByText("Opération de test réussie")).toBeVisible();
  expect(regionContenant("status", "Opération de test réussie")).toBeDefined();
  expect(regionContenant("alert", "Opération de test réussie")).toBeUndefined();
});

it("test_une_notification_d_erreur_est_annoncee_en_alerte", () => {
  rendreFournisseur();

  notifier({ type: "erreur", message: "Échec de test" });

  expect(screen.getByText("Échec de test")).toBeVisible();
  expect(regionContenant("alert", "Échec de test")).toBeDefined();
});

it("test_fermer_la_notification_la_retire", async () => {
  const user = userEvent.setup();
  rendreFournisseur();

  notifier({ type: "info", message: "Notification de test à fermer au clic" });
  await user.click(screen.getByRole("button", { name: "Fermer la notification" }));
  expect(screen.queryByText("Notification de test à fermer au clic")).not.toBeInTheDocument();

  notifier({ type: "info", message: "Notification de test à fermer au clavier" });
  act(() => {
    screen.getByRole("button", { name: "Fermer la notification" }).focus();
  });
  await user.keyboard("{Enter}");
  expect(screen.queryByText("Notification de test à fermer au clavier")).not.toBeInTheDocument();
});

it("test_une_notification_de_succes_disparait_apres_sa_duree", () => {
  vi.useFakeTimers();
  rendreFournisseur();

  notifier({ type: "succes", message: "Opération de test réussie" });
  avancer(DUREE_NOTIFICATION_MS - 1);
  expect(screen.getByText("Opération de test réussie")).toBeInTheDocument();
  avancer(1);

  expect(screen.queryByText("Opération de test réussie")).not.toBeInTheDocument();
});

it("test_une_notification_d_erreur_ne_disparait_pas_seule", () => {
  vi.useFakeTimers();
  rendreFournisseur();

  notifier({ type: "erreur", message: "Échec de test" });
  // Présente dès l'émission : sans cette vérification, l'absence de toute notification
  // ne serait pas distinguée d'une notification qui reste.
  expect(regionContenant("alert", "Échec de test")).toBeDefined();
  avancer(60_000);

  expect(screen.getByText("Échec de test")).toBeInTheDocument();
  expect(regionContenant("alert", "Échec de test")).toBeDefined();
});

it.each([{ cas: "survol" as const }, { cas: "focus sur Fermer la notification" as const }])(
  "test_le_survol_ou_le_focus_suspend_la_fermeture_automatique ($cas)",
  ({ cas }) => {
    // Faux minuteurs stricts : le survol passe par fireEvent (synchrone, déjà dans act) et non
    // par user-event, dont l'attente asynchrone ne progresse pas sous vi.useFakeTimers().
    vi.useFakeTimers();
    rendreFournisseur();
    const message = "Opération de test réussie";

    notifier({ type: "succes", message });
    avancer(3000);
    // Le message est dans la région de statut ; le survol vise le message lui-même, pour
    // atteindre la notification que la région permanente contient (validation 2).
    const region = regionContenant("status", message);
    expect(region).toBeDefined();
    const texte = screen.getByText(message);
    const fermer = screen.getByRole("button", { name: "Fermer la notification" });
    if (cas === "survol") {
      fireEvent.mouseEnter(texte);
    } else {
      act(() => {
        fermer.focus();
      });
    }
    avancer(7000);
    expect(screen.getByText(message)).toBeInTheDocument();

    if (cas === "survol") {
      fireEvent.mouseLeave(texte);
    } else {
      act(() => {
        fermer.blur();
      });
    }
    const restant = DUREE_NOTIFICATION_MS - 3000;
    avancer(restant - 1);
    expect(screen.getByText(message)).toBeInTheDocument();
    avancer(1);

    expect(screen.queryByText(message)).not.toBeInTheDocument();
  },
);

it("test_une_notification_ne_prend_pas_le_focus", () => {
  rendreFournisseur();
  const bouton = screen.getByRole("button", { name: "Bouton de test" });
  act(() => {
    bouton.focus();
  });

  notifier({ type: "succes", message: "Opération de test réussie" });

  // La notification doit être affichée : sinon le focus resterait trivialement en place.
  expect(screen.getByText("Opération de test réussie")).toBeVisible();
  expect(bouton).toHaveFocus();
});

it("test_plusieurs_notifications_s_empilent_dans_l_ordre", async () => {
  const user = userEvent.setup();
  rendreFournisseur();

  for (const numero of [1, 2, 3]) {
    notifier({ type: "info", message: `Notification de test ${String(numero)}` });
  }

  const messages = () =>
    screen.getAllByText(/^Notification de test \d$/).map((element) => element.textContent);
  expect(messages()).toEqual([
    "Notification de test 1",
    "Notification de test 2",
    "Notification de test 3",
  ]);
  const boutonsFermer = screen.getAllByRole("button", { name: "Fermer la notification" });
  expect(boutonsFermer).toHaveLength(3);
  await user.click(boutonsFermer[1] as HTMLElement);

  expect(messages()).toEqual(["Notification de test 1", "Notification de test 3"]);
});
