import type { APIRoute } from "astro";

import { loadAthletesDoc, loadMeetsDoc } from "../lib/data";
import { meetSlug } from "../lib/meet";

const BASE_URL = "https://es-kimo.github.io/splits/";

function absoluteUrl(path: string): string {
  return new URL(path, BASE_URL).toString();
}

function xmlEscape(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export const GET: APIRoute = () => {
  const { athletes } = loadAthletesDoc();
  const { items } = loadMeetsDoc();
  const urls = [
    "",
    "athlete/",
    "privacy/",
    "distribution/",
    "meet/",
    ...athletes.map((athlete) => athlete.url),
    ...items.map((item) => `meet/${meetSlug(item)}/`),
  ];
  const lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'];
  for (const path of urls) {
    lines.push(`  <url><loc>${xmlEscape(absoluteUrl(path))}</loc></url>`);
  }
  lines.push("</urlset>");
  return new Response(lines.join("\n"), {
    headers: { "Content-Type": "application/xml; charset=utf-8" },
  });
};
