import { defineConfig } from "astro/config";
import react from "@astrojs/react";

export default defineConfig({
  site: "https://splits.kr",
  base: "/",
  output: "static",
  trailingSlash: "always",
  build: {
    inlineStylesheets: "always",
  },
  integrations: [react()],
});
