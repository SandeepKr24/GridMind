"use client";

import Link from "next/link";
import { useCallback } from "react";
import { getCalendar } from "@/lib/api/races";
import { useAsync } from "@/lib/hooks/useAsync";
import { useSettings } from "@/components/SettingsProvider";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import {
  EmptyState,
  IngestionBadge,
  Panel,
  SkeletonRows,
} from "@/components/ui/primitives";
import type { CalendarRound, IngestionState } from "@/lib/api/types";

/**
 * The calendar is the one view that works against a completely empty database,
 * because the backend serves it without ingesting anything.
 */
export default function RacesPage() {
  const { season } = useSettings();
  const load = useCallback(() => getCalendar(season), [season]);
  const state = useAsync<CalendarRound[]>(load, [season]);

  return (
    <div className="flex flex-col gap-5">
      <header className="animate-fade">
        <h1 className="m-0 font-display text-[clamp(32px,5vw,52px)] font-bold uppercase leading-none">
          {season} Calendar
        </h1>
        <p className="mb-0 mt-1.5 text-sm text-ink-dim">
          Calendar data needs no ingestion. Opening an un-ingested round fetches its
          timing data first.
        </p>
      </header>

      <div className="flex flex-wrap gap-5 font-mono text-[10px] tracking-[0.14em] text-ink-ghost">
        <LegendItem state="ingested" note="Opens instantly" />
        <LegendItem state="available" note="Fetches on open · ~30-120s" />
        <LegendItem state="upcoming" note="Not yet raced" />
      </div>

      <AsyncBoundary state={state} loading={<CalendarSkeleton />}>
        {(rounds) =>
          rounds.length === 0 ? (
            <EmptyState
              title="No calendar available"
              body={`The backend returned no rounds for ${season}. It may not have calendar data for this season yet.`}
            />
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-px border border-line bg-line">
              {rounds.map((round) => (
                <RaceCard key={`${round.season}-${round.round}`} round={round} />
              ))}
            </div>
          )
        }
      </AsyncBoundary>
    </div>
  );
}

function LegendItem({ state, note }: { state: IngestionState; note: string }) {
  return (
    <div className="flex items-center gap-2">
      <IngestionBadge state={state} />
      <span className="text-ink-trace">{note}</span>
    </div>
  );
}

function RaceCard({ round }: { round: CalendarRound }) {
  const accent: Record<IngestionState, string> = {
    ingested: "bg-status-ready",
    available: "bg-status-pending",
    upcoming: "bg-status-idle",
  };

  const resultLine: Record<IngestionState, string> = {
    ingested: "Opens instantly",
    available: "Result not fetched",
    upcoming: "Awaiting lights out",
  };

  const body = (
    <>
      <span
        aria-hidden="true"
        className={`absolute bottom-0 left-0 top-0 w-[3px] ${accent[round.state]}`}
      />
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="font-mono text-[10px] tracking-[0.16em] text-ink-ghost">
          ROUND {round.round}
        </div>
        <IngestionBadge state={round.state} />
      </div>
      <div className="font-display text-[22px] uppercase leading-[1.05] tracking-[0.02em]">
        {round.event_name}
      </div>
      <div className="mt-1 text-xs text-ink-faint">{round.circuit_name}</div>
      <div className="mt-3 flex items-center justify-between font-mono text-[11px] text-ink-ghost">
        <span>{round.event_date}</span>
        <span>{resultLine[round.state]}</span>
      </div>
    </>
  );

  if (round.state === "upcoming") {
    return (
      <div className="relative animate-rise bg-surface-raised p-5 opacity-60">
        {body}
      </div>
    );
  }

  return (
    <Link
      href={`/races/${round.season}-${round.round}`}
      className="relative animate-rise bg-surface-raised p-5 no-underline transition-colors hover:bg-surface-hover"
    >
      {body}
    </Link>
  );
}

function CalendarSkeleton() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-px border border-line bg-line">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <Panel key={i} className="border-0 p-5">
          <SkeletonRows count={3} />
        </Panel>
      ))}
    </div>
  );
}
