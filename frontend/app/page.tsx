"use client";

import Link from "next/link";
import { useCallback } from "react";
import { getDashboard } from "@/lib/api/races";
import { useAsync } from "@/lib/hooks/useAsync";
import { useSettings } from "@/components/SettingsProvider";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import {
  Button,
  EmptyState,
  Panel,
  SectionHeading,
  SkeletonRows,
  StatCard,
} from "@/components/ui/primitives";
import type { DashboardSummary } from "@/lib/api/types";

export default function DashboardPage() {
  const { season, reducedMotion } = useSettings();
  const load = useCallback(() => getDashboard(season), [season]);
  const state = useAsync<DashboardSummary>(load, [season]);

  return (
    <div className="flex flex-col gap-5">
      <Hero reducedMotion={reducedMotion} />
      <AsyncBoundary state={state} loading={<DashboardSkeleton />}>
        {(data) => <DashboardContent data={data} />}
      </AsyncBoundary>
    </div>
  );
}

function Hero({ reducedMotion }: { reducedMotion: boolean }) {
  return (
    <section className="relative animate-fade overflow-hidden border border-line bg-surface-raised p-[clamp(28px,5vw,56px)]">
      <div
        aria-hidden="true"
        className="absolute inset-0 opacity-50"
        style={{
          backgroundImage:
            "repeating-linear-gradient(90deg,rgba(255,255,255,.035) 0px,rgba(255,255,255,.035) 1px,transparent 1px,transparent 60px)",
        }}
      />
      {!reducedMotion ? (
        <div
          aria-hidden="true"
          className="absolute left-0 top-0 h-0.5 w-[34%] animate-sweep bg-gradient-to-r from-transparent via-accent to-transparent"
        />
      ) : null}

      <div className="relative max-w-[760px]">
        <div className="mb-[18px] font-mono text-[11px] tracking-[0.24em] text-accent">
          LIVE DATA · ON DEMAND
        </div>
        <h1 className="m-0 mb-5 font-display text-[clamp(44px,8vw,96px)] font-bold uppercase leading-[0.92] tracking-[-0.01em]">
          Ask questions.
          <br />
          Explore the data.
          <br />
          <span className="text-ink-dim">Understand the race.</span>
        </h1>
        <p className="m-0 mb-[30px] max-w-[520px] text-base leading-[1.55] text-ink-muted text-pretty">
          No season pickers, no funnels. Ask in plain English — the analyst works out
          which session it needs and pulls the timing data.
        </p>
        <div className="flex flex-wrap gap-2.5">
          <Link href="/chat">
            <Button>Ask the Analyst</Button>
          </Link>
          <Link href="/races">
            <Button variant="ghost">Browse Races</Button>
          </Link>
        </div>
      </div>
    </section>
  );
}

function DashboardContent({ data }: { data: DashboardSummary }) {
  const stats = [
    {
      label: "ROUNDS INGESTED",
      value: String(data.rounds_ingested),
      sub: `of ${data.rounds_on_calendar} on the calendar`,
    },
    {
      label: "LAPS STORED",
      value: data.laps_stored.toLocaleString(),
      sub: "timing rows available offline",
    },
    {
      label: "AVG COLD FETCH",
      value:
        data.average_cold_fetch_seconds === null
          ? "—"
          : `${Math.round(data.average_cold_fetch_seconds)}s`,
      sub: "session pull from the timing API",
    },
    {
      label: "REPORTS WRITTEN",
      value: String(data.reports_written),
      sub: "stored permanently once generated",
    },
  ];

  return (
    <>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-px border border-line bg-line">
        {stats.map((s) => (
          <StatCard key={s.label} {...s} />
        ))}
      </div>

      <div className="mt-5 grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-5">
        <Panel className="p-[22px]">
          <SectionHeading right={data.latest_race?.event_name.toUpperCase()}>
            Latest Podium
          </SectionHeading>
          {data.latest_podium.length === 0 ? (
            <EmptyState
              title="No results yet"
              body="Nothing has been ingested for this season. Ask the analyst about a race and the timing data will be fetched on the spot."
              action={
                <Link href="/chat">
                  <Button variant="quiet">ASK THE ANALYST</Button>
                </Link>
              }
            />
          ) : (
            <div className="flex flex-col gap-px bg-line-faint">
              {data.latest_podium.slice(0, 3).map((row) => (
                <div
                  key={row.position}
                  className="flex animate-rise items-center gap-3.5 bg-surface-inset px-4 py-3.5"
                >
                  <div className="w-[30px] font-display text-[30px] font-bold text-accent">
                    {row.position}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-display text-[19px] uppercase tracking-[0.04em]">
                      {row.driver_name}
                    </div>
                    <div className="text-xs text-ink-faint">{row.constructor_name}</div>
                  </div>
                  <div className="font-mono text-xs text-ink-muted">
                    {row.gap_to_leader ?? "—"}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel className="flex flex-col p-[22px]">
          <SectionHeading>Latest Report</SectionHeading>
          {data.latest_report === null ? (
            <EmptyState
              title="No report yet"
              body="Reports are written automatically once a race concludes, and on request for historic races."
              action={
                <Link href="/races">
                  <Button variant="quiet">PICK A RACE</Button>
                </Link>
              }
            />
          ) : (
            <>
              <div className="mb-3 font-display text-[26px] uppercase leading-[1.1]">
                {data.latest_report.event_name}
              </div>
              <p className="m-0 mb-[18px] text-sm leading-[1.6] text-ink-muted text-pretty">
                {data.latest_report.sections[0]?.body ?? ""}
              </p>
              <div className="mt-auto">
                <Link href={`/reports/${data.latest_report.id}`}>
                  <Button variant="quiet">READ REPORT</Button>
                </Link>
              </div>
            </>
          )}
        </Panel>
      </div>
    </>
  );
}

function DashboardSkeleton() {
  return (
    <>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-px border border-line bg-line">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="bg-surface-raised px-[22px] py-5">
            <SkeletonRows count={2} />
          </div>
        ))}
      </div>
      <div className="mt-5 grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-5">
        <Panel className="p-[22px]">
          <SkeletonRows count={4} />
        </Panel>
        <Panel className="p-[22px]">
          <SkeletonRows count={4} />
        </Panel>
      </div>
    </>
  );
}
