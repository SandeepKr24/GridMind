import { readdirSync } from "node:fs";

/**
 * Team logo files present in public/teams, read once at build (and at dev
 * start) so lib/teams.ts knows which teams have one without requesting
 * missing files. Add a logo by dropping in `<key>.svg` or `<key>.png`.
 */
function teamLogos() {
  try {
    return readdirSync(new URL("./public/teams", import.meta.url)).join(",");
  } catch {
    return ""; // no folder yet: every team uses its colour mark
  }
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Stop `next dev` from writing AGENTS.md / CLAUDE.md into the project.
  agentRules: false,
  env: {
    NEXT_PUBLIC_TEAM_LOGOS: teamLogos(),
  },
  images: {
    // Official driver headshots, linked from Formula 1's media server (the
    // URLs OpenF1 publishes). Served as-is with `unoptimized`; this list only
    // stops next/image accepting any other remote host.
    remotePatterns: [new URL("https://media.formula1.com/**")],
  },
};

export default nextConfig;
