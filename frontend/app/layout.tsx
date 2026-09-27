import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Titillium_Web } from "next/font/google";
import { AppShell } from "@/components/AppShell";
import { SettingsProvider } from "@/components/SettingsProvider";
import "lenis/dist/lenis.css";
import "./globals.css";

// Body and interface text. Stays legible at small sizes, which labels and
// table headers need. Variable font, so no weight list.
const body = Inter({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

// Headings and names. Titillium is not a variable font, so weights are listed.
const display = Titillium_Web({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-display",
  display: "swap",
});

// Data only: lap times, positions, timers. Monospaced digits keep columns aligned.
const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "GridMind — AI Race Analyst",
  description:
    "Ask questions about Formula 1 races in plain English. Answers come from stored timing data, never invented.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${body.variable} ${display.variable} ${mono.variable}`}>
      <body>
        <SettingsProvider>
          <AppShell>{children}</AppShell>
        </SettingsProvider>
      </body>
    </html>
  );
}
