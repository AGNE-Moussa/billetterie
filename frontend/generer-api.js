// npm run api:gen : un fichier de types TypeScript par contrat services/<service>/openapi.yaml,
// écrit dans src/api/genere/<service>.ts (openapi-typescript), et un index src/api/genere/index.ts
// dont le type `CheminsApi` est l'intersection (`&`) des `paths` de tous les services (un nouveau
// contrat y entre sans édition à la main). La génération échoue si deux contrats déclarent le
// même chemin d'API (`/api/...`, ceux que le front appelle) ; les routes techniques que chaque
// service déclare (`/health`...) ne comptent pas. Fichiers commités ; la CI relance la
// génération et vérifie qu'ils sont à jour.
//
// Options (pour vérifier la génération sur des copies de contrats, sans toucher au dépôt) :
//   --contrats <dossier>  dossier contenant <service>/openapi.yaml (défaut : ../services)
//   --sortie <dossier>    dossier des fichiers générés (défaut : src/api/genere)
// Les chemins relatifs sont résolus depuis le dossier courant.
import { mkdir, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

import openapiTS, { astToString } from "openapi-typescript";
import { format, resolveConfig } from "prettier";
import ts from "typescript";

const ICI = dirname(fileURLToPath(import.meta.url));
const DOSSIER_GENERE_DEFAUT = join(ICI, "src", "api", "genere");

const { values: options } = parseArgs({
  options: {
    contrats: { type: "string" },
    sortie: { type: "string" },
  },
  strict: true,
});
const DOSSIER_SERVICES =
  options.contrats === undefined ? join(ICI, "..", "services") : resolve(options.contrats);
const DOSSIER_GENERE =
  options.sortie === undefined ? DOSSIER_GENERE_DEFAUT : resolve(options.sortie);
// Libellés des journaux : inchangés par défaut, chemin absolu (séparateurs `/`, comme le reste
// du message) si une option les déplace.
const LIBELLE_SERVICES =
  options.contrats === undefined ? "services" : DOSSIER_SERVICES.replaceAll(sep, "/");
const LIBELLE_GENERE =
  options.sortie === undefined ? "src/api/genere" : DOSSIER_GENERE.replaceAll(sep, "/");

/** Préfixe des chemins appelés par le front : seuls eux doivent être disjoints entre contrats. */
const PREFIXE_API = "/api/";

const ENTETE =
  "// Fichier généré par `npm run api:gen` depuis services/%SERVICE%/openapi.yaml.\n" +
  "// Ne pas modifier à la main : modifier le contrat puis relancer la génération.\n\n";

/** En-tête de index.ts : il sert aussi de repère d'un dossier déjà généré par ce script. */
const ENTETE_INDEX =
  "// Fichier généré par `npm run api:gen` : un import par contrat services/*/openapi.yaml.\n" +
  "// Ne pas modifier à la main : ajouter le contrat puis relancer la génération.\n\n";

async function existe(chemin) {
  try {
    await stat(chemin);
    return true;
  } catch {
    return false;
  }
}

async function contrats() {
  const entrees = await readdir(DOSSIER_SERVICES, { withFileTypes: true });
  const trouves = [];
  for (const entree of entrees.filter((e) => e.isDirectory())) {
    const contrat = join(DOSSIER_SERVICES, entree.name, "openapi.yaml");
    if (await existe(contrat)) {
      trouves.push({ service: entree.name, contrat });
    }
  }
  return trouves.sort((a, b) => a.service.localeCompare(b.service));
}

/** Écrit `contenu` dans `cible`, formaté avec la configuration Prettier du projet. */
async function ecrireFormate(cible, contenu) {
  // `npm run lint` vérifie le format comme le reste de src/, et la sortie reste stable d'une
  // génération à l'autre. La configuration est celle du dossier par défaut, même si `--sortie`
  // écrit ailleurs : le format ne dépend pas du dossier de sortie.
  const config = (await resolveConfig(join(DOSSIER_GENERE_DEFAUT, "index.ts"))) ?? {};
  await writeFile(cible, await format(contenu, { ...config, filepath: cible }), "utf8");
}

/** Identifiant TypeScript du type `paths` d'un service : `catalogue-salles` -> `CheminsCatalogueSalles`. */
function identifiantChemins(service) {
  const mots = service.split(/[^A-Za-z0-9]+/).filter((mot) => mot !== "");
  return `Chemins${mots.map((mot) => mot[0].toUpperCase() + mot.slice(1)).join("")}`;
}

/** Index : `CheminsApi`, intersection des `paths` de tous les services (chemins disjoints). */
async function genererIndex(liste) {
  const imports = liste
    .map(
      ({ service }) =>
        `import type { paths as ${identifiantChemins(service)} } from "./${service}";`,
    )
    .join("\n");
  const intersection = liste.map(({ service }) => identifiantChemins(service)).join(" & ");
  const contenu =
    ENTETE_INDEX +
    `${imports}\n\n` +
    "/** Chemins de tous les contrats (les `paths` de chaque service, réunis). */\n" +
    `export type CheminsApi = ${intersection};\n`;
  await ecrireFormate(join(DOSSIER_GENERE, "index.ts"), contenu);
  console.log(`${LIBELLE_GENERE}/index.ts généré (CheminsApi)`);
}

/** Chemins déclarés par un contrat : les membres de l'interface `paths` générée. */
function cheminsDeclares(ast) {
  const interfacePaths = ast.find(
    (noeud) => ts.isInterfaceDeclaration(noeud) && noeud.name.text === "paths",
  );
  if (interfacePaths === undefined) {
    return [];
  }
  return interfacePaths.members
    .map((membre) => membre.name)
    .filter((nom) => nom !== undefined && (ts.isStringLiteral(nom) || ts.isIdentifier(nom)))
    .map((nom) => nom.text);
}

/**
 * Échoue si deux contrats déclarent le même chemin d'API : `CheminsApi` est une intersection, un
 * chemin commun y fusionnerait en silence les opérations des deux services. Seuls les chemins
 * `/api/...` sont contrôlés : `/health` et les autres routes techniques, déclarées à l'identique
 * par chaque service, ne sont pas appelées par le front.
 */
function verifierCheminsDisjoints(generes) {
  const proprietaires = new Map();
  const doublons = [];
  for (const { service, ast } of generes) {
    for (const chemin of cheminsDeclares(ast).filter((c) => c.startsWith(PREFIXE_API))) {
      const premier = proprietaires.get(chemin);
      if (premier === undefined) {
        proprietaires.set(chemin, service);
      } else {
        doublons.push(
          `  ${chemin} : ${LIBELLE_SERVICES}/${premier} et ${LIBELLE_SERVICES}/${service}`,
        );
      }
    }
  }
  if (doublons.length > 0) {
    throw new Error(
      "Chemin d'API déclaré par plusieurs contrats openapi.yaml (chaque chemin /api/ " +
        `appartient à un seul service) :\n${doublons.join("\n")}`,
    );
  }
}

/**
 * Refuse de vider un dossier de sortie qui n'est pas le nôtre : `--sortie` mal saisi ne doit pas
 * effacer un dossier quelconque. Accepté : dossier absent, dossier vide, ou dossier dont
 * l'index.ts commence par l'en-tête écrit par ce script. Sinon, erreur et rien n'est supprimé.
 */
async function verifierDossierSortie() {
  let entrees;
  try {
    entrees = await readdir(DOSSIER_GENERE);
  } catch (erreur) {
    if (erreur.code === "ENOENT") {
      return;
    }
    if (erreur.code === "ENOTDIR") {
      throw new Error(
        `${LIBELLE_GENERE} existe et n'est pas un dossier : génération refusée, rien n'est supprimé.`,
        { cause: erreur },
      );
    }
    throw erreur;
  }
  if (entrees.length === 0) {
    return;
  }
  let index = "";
  try {
    index = await readFile(join(DOSSIER_GENERE, "index.ts"), "utf8");
  } catch {
    // Pas d'index.ts lisible : ce n'est pas un dossier généré par ce script.
  }
  if (!index.replaceAll("\r\n", "\n").startsWith(ENTETE_INDEX)) {
    throw new Error(
      `${LIBELLE_GENERE} n'est pas vide et n'est pas un dossier généré par \`npm run api:gen\` ` +
        "(pas d'index.ts portant son en-tête) : génération refusée, rien n'est supprimé. " +
        "Choisir avec --sortie un dossier absent, vide ou déjà généré.",
    );
  }
}

async function generer() {
  const liste = await contrats();
  if (liste.length === 0) {
    throw new Error(`Aucun contrat <service>/openapi.yaml sous ${DOSSIER_SERVICES}`);
  }
  const generes = [];
  for (const { service, contrat } of liste) {
    const ast = await openapiTS(pathToFileURL(contrat), {
      rootTypes: true,
      rootTypesNoSchemaPrefix: true,
    });
    generes.push({ service, ast });
  }
  // Vérifier avant d'écrire : un échec laisse les fichiers générés précédents intacts.
  verifierCheminsDisjoints(generes);
  await verifierDossierSortie();
  // Repartir d'un dossier vide : un service retiré ne laisse pas de types orphelins.
  await rm(DOSSIER_GENERE, { recursive: true, force: true });
  await mkdir(DOSSIER_GENERE, { recursive: true });
  for (const { service, ast } of generes) {
    const cible = join(DOSSIER_GENERE, `${service}.ts`);
    await ecrireFormate(cible, ENTETE.replace("%SERVICE%", service) + astToString(ast));
    console.log(
      `${LIBELLE_GENERE}/${service}.ts généré depuis ${LIBELLE_SERVICES}/${service}/openapi.yaml`,
    );
  }
  await genererIndex(liste);
}

await generer();
