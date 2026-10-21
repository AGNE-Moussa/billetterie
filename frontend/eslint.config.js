// Règles ESLint du front (configuration « flat »). BIL-F26 y ajoutera React et les hooks.
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "node_modules/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
);
