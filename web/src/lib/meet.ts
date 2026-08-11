import type { MeetItem } from "./types";

function normalizeMeetText(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}\s-]/gu, " ")
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
  if (item.slug) return item.slug;
  const normalized = normalizeMeetText(item.meet || "meet");
  const base = normalized.split("-").find((part) => part.length > 0) || "meet";
  const hash = hashText(`${item.year}-${item.meet}`).slice(0, 6);
  return `${item.year}-${base}-${hash}`;
}

export function classifyMeetKind(meetName: string): string {
  const text = String(meetName || "").trim();
  if (text.includes("국가대표") && text.includes("선발")) return "국가대표 선발";
  if (text.includes("전국동계체육대회")) return "전국체전";
  if (text.includes("선수권")) return "선수권";
  if (text.includes("종별")) return "종별";
  if (text.includes("회장배")) return "회장배";
  if (text.includes("국무총리배")) return "국무총리배";
  return "기타";
}

export function isNationalMeetKind(kind: string): boolean {
  return kind === "국가대표 선발" || kind === "전국체전" || kind === "선수권";
}

export function formatMeetDateRange(start: string | null, end: string | null): string {
  if (!start && !end) return "일자 정보 없음";
  if (start && end && start !== end) return `${start} ~ ${end}`;
  return start || end || "일자 정보 없음";
}

export function shortenMeetTitle(meetName: string): string {
  return String(meetName || "")
    .replace(/^KB금융그룹\s*/u, "")
    .replace(/\s+겸\s+/gu, " · ")
    .replace(/\s+/gu, " ")
    .trim();
}
