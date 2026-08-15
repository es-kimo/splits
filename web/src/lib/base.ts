export function withBase(path = ""): string {
  const cleaned = String(path).replace(/^\/+/, "");
  return `${import.meta.env.BASE_URL}${cleaned}`;
}

const SITE_ORIGIN = import.meta.env.SITE || "https://splits.kr";

function isAbsoluteUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

export function toAbsoluteUrl(pathOrUrl = ""): string {
  const value = String(pathOrUrl || "").trim();
  if (isAbsoluteUrl(value)) return value;
  const basePath = value ? withBase(value) : withBase();
  return new URL(basePath, SITE_ORIGIN).toString();
}
