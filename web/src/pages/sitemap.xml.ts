import type { APIRoute } from "astro";

import { loadAthletesDoc, loadMeetsDoc } from "../lib/data";
import { meetSlug } from "../lib/meet";

const BASE_URL = "https://splits.kr/";

function absoluteUrl(path: string): string {
  return new URL(path, BASE_URL).toString();
}

function xmlEscape(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export const GET: APIRoute = () => {
  const { athletes } = loadAthletesDoc();
  const { items } = loadMeetsDoc();
  const athleteUrls = [...new Set(athletes.map((athlete) => `athlete/${athlete.slug}/`))];
  // distribution/ 은 홈으로 합쳐졌습니다. 리다이렉트 페이지라 사이트맵에서 뺍니다.
  const urls = [
    "",
    "analysis/",
    "ranking/",
    "athlete/",
    "privacy/",
    "meet/",
    ...athleteUrls,
    ...items.map((item) => item.url || `meet/${meetSlug(item)}/`),
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
