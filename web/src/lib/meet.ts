import type { MeetItem } from "./types";

function normalizeMeetText(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9\s-]/g, " ")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

function hashText(value: string): string {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash >>> 0).toString(36);
}

export function meetSlug(item: MeetItem): string {
  const normalized = normalizeMeetText(item.meet);
  const base = normalized.split("-").find((part) => part.length > 0) || "meet";
  const hash = hashText(`${item.year}-${item.meet}`).slice(0, 6);
  return `${item.year}-${base}-${hash}`;
}
