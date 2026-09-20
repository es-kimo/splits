import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import type { AthletesDoc, DistributionDoc, MeetsDoc, MetaDoc, RankingDoc, ReverseDistributionDoc } from "./types";

const REPO_ROOT = new URL("../../../", import.meta.url);
const SITE_DATA_DIR = new URL("site/data/", REPO_ROOT);

function readJson<T>(fileName: string): T {
  const fileUrl = new URL(fileName, SITE_DATA_DIR);
  const raw = readFileSync(fileURLToPath(fileUrl), "utf-8");
  return JSON.parse(raw) as T;
}

export function loadAthletesDoc(): AthletesDoc {
  return readJson<AthletesDoc>("athletes.json");
}

export function loadMeetsDoc(): MeetsDoc {
  return readJson<MeetsDoc>("meets.json");
}

export function loadDistributionDoc(): DistributionDoc {
  return readJson<DistributionDoc>("distribution.json");
}

export function loadReverseDistributionDoc(): ReverseDistributionDoc {
  return readJson<ReverseDistributionDoc>("reverse_distribution.json");
}

export function loadMetaDoc(): MetaDoc {
  return readJson<MetaDoc>("meta.json");
}

export function loadRankingDoc(): RankingDoc {
  return readJson<RankingDoc>("ranking.json");
}
