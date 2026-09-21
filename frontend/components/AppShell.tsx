"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useSettings } from "@/components/SettingsProvider";
import { availableSeasons } from "@/lib/hooks/useSeason";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/races", label: "Races" },
  { href: "/chat", label: "Analyst" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const { soundEnabled, toggleSound, reducedMotion, season, setSeason } = useSettings();
  const pathname = usePathname();

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <div className="relative min-h-screen bg-surface-base">
      {!reducedMotion ? (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed inset-0 z-[1] animate-drift opacity-[0.35]"
          style={{
            backgroundImage:
              "repeating-linear-gradient(180deg,rgba(255,255,255,.028) 0px,rgba(255,255,255,.028) 1px,transparent 1px,transparent 4px)",
          }}
        />
      ) : null}

      <header className="sticky top-0 z-40 border-b border-line bg-surface-base/[0.92] backdrop-blur-[10px]">
        <div className="mx-auto flex min-h-[60px] max-w-[1400px] flex-wrap items-center gap-[22px] px-5">
          <Link href="/" className="mr-1 flex items-center gap-2.5 no-underline">
            <div className="h-[22px] w-[5px] bg-accent" aria-hidden="true" />
            <div className="font-display text-[22px] font-bold uppercase tracking-[0.14em] text-ink">
              Gridmind
            </div>
            <div className="hidden rounded-sm border border-line-strong px-[5px] py-0.5 font-mono text-[9px] tracking-[0.18em] text-ink-ghost sm:block">
              AI RACE ANALYST
            </div>
          </Link>

          <nav className="flex min-w-[200px] flex-1 flex-wrap gap-0.5">
            {NAV.map((item) => {
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`relative px-3.5 py-2.5 font-display text-sm font-semibold uppercase tracking-[0.14em] no-underline ${
                    active
                      ? "border-b-2 border-accent bg-surface-hover text-ink"
                      : "text-ink hover:bg-surface-hover"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-2.5">
            <label className="flex items-center gap-2 font-mono text-[11px] tracking-[0.08em] text-ink-ghost">
              <span>SEASON</span>
              <select
                value={season}
                onChange={(e) => setSeason(Number(e.target.value))}
                className="rounded-sm border border-line-strong bg-surface-inset px-2 py-1.5 font-mono text-[11px] text-ink-muted hover:text-ink"
              >
                {availableSeasons().map((year) => (
                  <option key={year} value={year}>
                    {year}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={toggleSound}
              aria-pressed={soundEnabled}
              className="rounded-sm border border-line-strong bg-surface-inset px-2.5 py-1.5 font-mono text-[10px] tracking-[0.12em] text-ink-muted hover:text-ink"
            >
              SOUND {soundEnabled ? "ON" : "OFF"}
            </button>
          </div>
        </div>
      </header>

      <main className="relative z-[2] mx-auto max-w-[1400px] px-5 pb-20 pt-7">
        {children}
      </main>
    </div>
  );
}
