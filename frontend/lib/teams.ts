/**
 * Team identity: which team a name refers to, its colour, and its logo file.
 *
 * The backend sends team names as plain text (and chat tables carry nothing
 * else), and a team's name changes with sponsors and owners, so names are
 * matched against every spelling used since 2018. Earlier identities of a
 * renamed team (Toro Rosso, AlphaTauri, Alfa Romeo, Racing Point...) keep their
 * own key, because their logos differ.
 *
 * Logos: put `<key>.svg` or `<key>.png` in `frontend/public/teams/`, using
 * the keys below, and commit it. `next.config.mjs` lists that folder at build
 * time, so no code change is needed. A team without a file is shown with a
 * bar in its livery colour.
 */

export type TeamKey =
  | "mercedes"
  | "ferrari"
  | "red_bull"
  | "mclaren"
  | "aston_martin"
  | "alpine"
  | "williams"
  | "rb"
  | "sauber"
  | "haas"
  | "cadillac"
  | "audi"
  | "racing_point"
  | "force_india"
  | "renault"
  | "toro_rosso"
  | "alphatauri"
  | "alfa_romeo";

/** Livery colours, used for the mark when a team has no logo file. */
const COLORS: Record<TeamKey, string> = {
  mercedes: "#27F4D2",
  ferrari: "#E8002D",
  red_bull: "#3671C6",
  mclaren: "#FF8000",
  aston_martin: "#229971",
  alpine: "#0093CC",
  williams: "#64C4FF",
  rb: "#6692FF",
  sauber: "#52E252",
  haas: "#B6BABD",
  cadillac: "#C8C8C8",
  audi: "#BB0A30",
  racing_point: "#F596C8",
  force_india: "#F596C8",
  renault: "#FFF500",
  toro_rosso: "#469BFF",
  alphatauri: "#5E8FAA",
  alfa_romeo: "#C92D4B",
};

const NEUTRAL = "#3A4049";

/** Every spelling seen for each team, normalised by `normalise` below. */
const ALIASES: Record<TeamKey, string[]> = {
  mercedes: ["mercedes", "mercedesamg", "mercedesamgpetronas", "mercedesamgpetronasf1team"],
  ferrari: ["ferrari", "scuderiaferrari", "scuderiaferrarihp"],
  red_bull: ["redbull", "redbullracing", "redbullracinghonda", "oracleredbullracing"],
  mclaren: ["mclaren", "mclarenf1team", "mclarenmercedes", "mclarenrenault"],
  aston_martin: ["astonmartin", "astonmartinaramco", "astonmartinaramcof1team"],
  alpine: ["alpine", "alpinef1team", "alpinerenault", "bwtalpinef1team"],
  williams: ["williams", "williamsracing", "williamsmercedes", "atlassianwilliamsracing"],
  rb: ["rb", "rbf1team", "racingbulls", "visacashapprb", "visacashappracingbulls"],
  sauber: ["sauber", "kicksauber", "stakef1team", "stakef1teamkicksauber"],
  haas: ["haas", "haasf1team", "haasferrari", "moneygramhaasf1team"],
  cadillac: ["cadillac", "cadillacf1team"],
  audi: ["audi", "audif1team"],
  racing_point: ["racingpoint", "bwtracingpoint", "racingpointf1team"],
  force_india: ["forceindia", "saharaforceindia"],
  renault: ["renault", "renaultf1team"],
  toro_rosso: ["tororosso", "scuderiatororosso"],
  alphatauri: ["alphatauri", "scuderiaalphatauri"],
  alfa_romeo: ["alfaromeo", "alfaromeoracing", "alfaromeoracingorlen", "alfaromeof1teamstake"],
};

const normalise = (name: string) => name.toLowerCase().replace(/[^a-z0-9]/g, "");

const BY_ALIAS = new Map<string, TeamKey>(
  (Object.entries(ALIASES) as [TeamKey, string[]][]).flatMap(([key, names]) =>
    names.map((alias) => [alias, key] as const)
  )
);

export function teamKey(name: string): TeamKey | null {
  return BY_ALIAS.get(normalise(name)) ?? null;
}

export function teamColor(key: TeamKey | null): string {
  return key ? COLORS[key] : NEUTRAL;
}

/** Logo files by key, from a comma-separated list of file names. */
export function parseLogoList(list: string | undefined): Map<string, string> {
  const found = new Map<string, string>();
  for (const file of (list ?? "").split(",")) {
    const name = file.trim();
    const match = /^(?<key>[a-z0-9_]+)\.(?<ext>svg|png)$/.exec(name);
    const key = match?.groups?.key;
    if (!key) continue;
    // SVG wins: it stays sharp at any size.
    if (match.groups?.ext === "svg" || !found.has(key)) found.set(key, name);
  }
  return found;
}

/** Filled in by next.config.mjs from the files in public/teams. */
const AVAILABLE = parseLogoList(process.env.NEXT_PUBLIC_TEAM_LOGOS);

export function teamLogoSrc(
  key: TeamKey | null,
  available: Map<string, string> = AVAILABLE
): string | null {
  const file = key ? available.get(key) : undefined;
  return file ? `/teams/${file}` : null;
}
