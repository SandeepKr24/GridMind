import type { MetadataRoute } from "next";

/**
 * Web app manifest, so "Add to home screen" and install use the GridMind icon
 * and colours. The favicon, SVG icon and Apple icon are separate files in
 * app/ (favicon.ico, icon.svg, apple-icon.png), which Next.js links itself.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "GridMind — AI Race Analyst",
    short_name: "GridMind",
    description: "Ask questions about Formula 1 races in plain English.",
    start_url: "/",
    display: "standalone",
    background_color: "#0A0B0D",
    theme_color: "#0A0B0D",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
