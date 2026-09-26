/**
 * Display formatting for values the backend sends as raw strings.
 *
 * Built by hand in UTC rather than with Intl: the report page renders on the
 * server and again in the browser, and both a viewer-local time zone and
 * differing ICU data ("Sep" vs "Sept" in en-GB) would make the two disagree,
 * which React reports as a hydration mismatch.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const pad = (n: number) => String(n).padStart(2, "0");

/** "2026-09-26T14:51:02+00:00" -> "26 Sep 2026, 14:51 UTC". */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const day = `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
  return `${day}, ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
}
