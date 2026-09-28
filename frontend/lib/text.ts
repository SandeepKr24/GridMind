/**
 * The site uses no en or em dashes. Our own copy is written without them;
 * this catches text the backend sends, including model-written replies and
 * reports stored before the rule existed.
 */
export function stripDashes(text: string): string {
  return text
    .replace(/\s+[–—]\s+/g, ", ")
    .replace(/[–—]/g, "-");
}

/** `stripDashes` applied to every string in a parsed JSON value. */
export function stripDashesDeep<T>(value: T): T {
  if (typeof value === "string") return stripDashes(value) as T;
  if (Array.isArray(value)) return value.map(stripDashesDeep) as T;
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, v]) => [key, stripDashesDeep(v)])
    ) as T;
  }
  return value;
}
