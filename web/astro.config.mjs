import { defineConfig } from "astro/config";
import react from "@astrojs/react";

export default defineConfig({
  site: "https://es-kimo.github.io",
  base: "/splits",
  output: "static",
  trailingSlash: "always",
  integrations: [react()],
});
