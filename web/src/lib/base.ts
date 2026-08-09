export function withBase(path = ""): string {
  const cleaned = String(path).replace(/^\/+/, "");
  return `${import.meta.env.BASE_URL}${cleaned}`;
}
