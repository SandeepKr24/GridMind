"use client";

import Link from "next/link";
import { Suspense, useCallback, useState } from "react";
import { useParams } from "next/navigation";
import { getRace, getRaceStats } from "@/lib/api/races";
import { generateReport, getRaceReport } from "@/lib/api/reports";
import { triggerIngest } from "@/lib/api/jobs";
import { describeError } from "@/lib/api/client";
import { useAsync } from "@/lib/hooks/useAsync";
import { useIngestionJob } from "@/lib/hooks/useIngestionJob";
import { askHref, isValidJobId, useUrlParam } from "@/lib/hooks/useUrlParam";
import { AsyncBoundary, isNotFound } from "@/components/AsyncBoundary";
import { LoadingPit } from "@/components/LoadingPit";
import {
  Button,
  EmptyState,
  ErrorState,
  IngestionBadge,
  Panel,
  SectionHeading,
  SkeletonRows,
} from "@/components/ui/primitives";
import {
  LapPaceChart,
  PositionChangeChart,
  TyreStrategyChart,
} from "@/components/race/RaceCharts";
import {
  ClassificationTable,
  PitStopTable,
  RaceControlList,
} from "@/components/race/RaceTables";
import { formatTimestamp } from "@/lib/format";
import type { RaceDetail, RaceStats, Report } from "@/lib/api/types";

const SECTIONS = [
  { id: "classification", label: "CLASSIFICATION" },
  { id: "positions", label: "POSITIONS" },
  { id: "pace", label: "PACE" },
  { id: "strategy", label: "STRATEGY" },
  { id: "pits", label: "PIT STOPS" },
  { id: "events", label: "EVENTS" },
  { id: "report", label: "REPORT" },
  { id: "ask", label: "ASK" },
] as const;

/** Route ids are "{season}-{round}", which the backend resolves to a session. */
function parseRaceId(id: string): { season: number; round: number } | null {
  const [season, round] = id.split("-");
  const s = Number(season);
  const r = Number(round);
  if (!Number.isFinite(s) || !Number.isFinite(r)) return null;
  return { season: s, round: r };
}

/**
 * The Suspense boundary is required: the page reads the job id from the URL
 * with useSearchParams, and Next 16 needs a boundary around that.
 */
export default function RaceDetailPage() {
  return (
    <Suspense fallback={<SkeletonRows count={5} />}>
      <RaceDetailContent />
    </Suspense>
  );
}

function RaceDetailContent() {
  const params = useParams<{ id: string }>();
  const raceId = params.id;

  // Held in the URL so a refresh mid-ingest reattaches to the running job.
  const [jobId, setJobId] = useUrlParam("job", isValidJobId);
  const [jobError, setJobError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);

  const loadRace = useCallback(() => getRace(raceId), [raceId]);
  const raceState = useAsync<RaceDetail>(loadRace, [raceId]);

  const onJobComplete = useCallback(
    (ok: boolean) => {
      if (ok) {
        setJobId(null);
        raceState.reload();
      }
    },
    [raceState, setJobId]
  );

  const job = useIngestionJob(jobId, onJobComplete);

  const startIngest = useCallback(async () => {
    const parsed = parseRaceId(raceId);
    if (!parsed) return;
    setJobError(null);
    setDismissed(false);
    try {
      const { job_id } = await triggerIngest({
        year: parsed.season,
        round: parsed.round,
        session: "race",
      });
      setJobId(job_id);
    } catch (err) {
      const { body } = describeError(err);
      setJobError(body);
    }
  }, [raceId, setJobId]);

  return (
    <div className="flex flex-col gap-6">
      <AsyncBoundary state={raceState} loading={<SkeletonRows count={5} />}>
        {(race) => (
          <>
            <RaceHeader race={race} />

            {jobError ? (
              <ErrorState
                title="COULD NOT START THE FETCH"
                body={jobError}
                onRetry={startIngest}
              />
            ) : null}

            {race.state === "ingested" ? (
              <IngestedRace race={race} raceId={raceId} />
            ) : (
              <NotIngested race={race} onFetch={startIngest} busy={job.isActive} />
            )}
          </>
        )}
      </AsyncBoundary>

      <LoadingPit
        active={(job.isActive || job.isFailed) && !dismissed}
        stage={job.stage}
        stageIndex={job.stageIndex}
        elapsedSeconds={job.elapsedSeconds}
        failed={job.isFailed}
        overdue={job.isOverdue}
        error={job.error}
        log={job.log}
        onRetry={startIngest}
        onDismiss={() => (job.isFailed ? setJobId(null) : setDismissed(true))}
      />
    </div>
  );
}

function RaceHeader({ race }: { race: RaceDetail }) {
  const facts = [
    { label: "LAPS", value: race.total_laps === null ? "—" : String(race.total_laps) },
    { label: "FASTEST LAP", value: race.fastest_lap_time ?? "—" },
    {
      label: "SAFETY CARS",
      value: race.safety_car_periods === null ? "—" : String(race.safety_car_periods),
    },
    { label: "MARGIN", value: race.winning_margin ?? "—" },
  ];

  return (
    <Panel className="animate-fade p-[clamp(20px,4vw,32px)]">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="gm-label">
            {race.season} · ROUND {race.round}
          </div>
          <h1 className="m-0 mt-2 font-display text-[clamp(30px,5vw,56px)] font-bold uppercase leading-none">
            {race.event_name}
          </h1>
          <div className="mt-2 text-sm text-ink-dim">
            {race.circuit_name} · {race.event_date}
          </div>
        </div>
        <IngestionBadge state={race.state} />
      </div>

      <div className="mt-6 grid grid-cols-[repeat(auto-fit,minmax(min(130px,100%),1fr))] gap-px bg-line">
        {facts.map((f) => (
          <div key={f.label} className="bg-surface-raised px-4 py-3">
            <div className="gm-label mb-1.5">{f.label}</div>
            <div className="font-mono text-lg text-ink">{f.value}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function NotIngested({
  race,
  onFetch,
  busy,
}: {
  race: RaceDetail;
  onFetch: () => void;
  busy: boolean;
}) {
  if (race.state === "upcoming") {
    return (
      <EmptyState
        title="Not yet raced"
        body="This round has not taken place. There is no timing data to fetch."
        action={
          <Link href="/races">
            <Button variant="quiet">BACK TO CALENDAR</Button>
          </Link>
        }
      />
    );
  }

  return (
    <Panel className="p-[clamp(20px,4vw,32px)]">
      <div className="mb-3.5 gm-label text-status-pending">
        SESSION NOT INGESTED
      </div>
      <div className="font-display text-[clamp(22px,3.5vw,30px)] font-semibold uppercase leading-tight">
        Timing data has not been fetched yet
      </div>
      <p className="mt-3 max-w-[560px] text-sm leading-relaxed text-ink-muted text-pretty">
        GridMind stores nothing until it is asked for. Fetching this session pulls
        results, laps, pit stops and race control messages from the timing API — it
        usually takes 30 to 120 seconds. Once stored, it is instant forever after.
      </p>
      <div className="mt-6">
        <Button onClick={onFetch} disabled={busy}>
          {busy ? "Fetching…" : "Fetch this session"}
        </Button>
      </div>
    </Panel>
  );
}

function IngestedRace({ race, raceId }: { race: RaceDetail; raceId: string }) {
  const loadStats = useCallback(() => getRaceStats(raceId), [raceId]);
  const statsState = useAsync<RaceStats>(loadStats, [raceId]);

  return (
    <>
      <nav
        aria-label="Sections"
        className="flex flex-wrap gap-0.5 border-y border-line py-2"
      >
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className="px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-ink-ghost no-underline hover:text-ink"
          >
            {s.label}
          </a>
        ))}
      </nav>

      <AsyncBoundary state={statsState} loading={<SkeletonRows count={8} />}>
        {(stats) => (
          <div className="flex flex-col gap-6">
            <Panel as="section" className="p-[22px]" id="classification">
              <SectionHeading>Classification</SectionHeading>
              <ClassificationTable rows={stats.classification} />
            </Panel>

            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(320px,100%),1fr))] gap-6">
              <Panel as="section" className="p-[22px]" id="positions">
                <SectionHeading>Position Changes</SectionHeading>
                <PositionChangeChart changes={stats.position_changes} />
              </Panel>

              <Panel as="section" className="p-[22px]" id="pace">
                <SectionHeading>Lap Pace</SectionHeading>
                <LapPaceChart traces={stats.pace_traces} />
              </Panel>
            </div>

            <Panel as="section" className="p-[22px]" id="strategy">
              <SectionHeading>Tyre Strategy</SectionHeading>
              <TyreStrategyChart
                strategies={stats.strategies}
                totalLaps={race.total_laps}
              />
            </Panel>

            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(320px,100%),1fr))] gap-6">
              <Panel as="section" className="p-[22px]" id="pits">
                <SectionHeading>Pit Stops</SectionHeading>
                <PitStopTable stops={stats.pit_stops} />
              </Panel>

              <Panel as="section" className="p-[22px]" id="events">
                <SectionHeading>Race Control</SectionHeading>
                <RaceControlList events={stats.race_control} />
              </Panel>
            </div>
          </div>
        )}
      </AsyncBoundary>

      <ReportSection raceId={raceId} eventName={race.event_name} />
      <AskAboutRace race={race} />
    </>
  );
}

function AskAboutRace({ race }: { race: RaceDetail }) {
  const name = `${race.season} ${race.event_name}`;
  const prompts = [
    `Who gained the most positions at the ${name}?`,
    `Which drivers used a one-stop strategy at the ${name}?`,
    `Who had the best race pace at the ${name}?`,
  ];

  return (
    <Panel as="section" className="p-[22px]" id="ask">
      <SectionHeading>Ask About This Race</SectionHeading>
      <div className="flex flex-col gap-px bg-line-faint">
        {prompts.map((prompt) => (
          <Link
            key={prompt}
            href={askHref(prompt)}
            className="bg-surface-inset px-4 py-3.5 text-sm text-ink-muted no-underline transition-colors hover:bg-surface-hover hover:text-ink"
          >
            {prompt}
          </Link>
        ))}
      </div>
    </Panel>
  );
}

function ReportSection({
  raceId,
  eventName,
}: {
  raceId: string;
  eventName: string;
}) {
  const [starting, setStarting] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  // Generation is a backend job. Its id lives in the URL, like ingestion jobs.
  const [reportJobId, setReportJobId] = useUrlParam("reportJob", isValidJobId);

  const load = useCallback(() => getRaceReport(raceId), [raceId]);
  const state = useAsync<Report>(load, [raceId]);

  const onReportDone = useCallback(
    (ok: boolean) => {
      if (ok) {
        setReportJobId(null);
        state.reload();
      }
    },
    [setReportJobId, state]
  );

  const reportJob = useIngestionJob(reportJobId, onReportDone);

  const onGenerate = useCallback(async () => {
    setStarting(true);
    setGenError(null);
    setDismissed(false);
    try {
      const { job_id } = await generateReport(raceId);
      setReportJobId(job_id);
    } catch (err) {
      setGenError(describeError(err).body);
    } finally {
      setStarting(false);
    }
  }, [raceId, setReportJobId]);

  const generating = starting || reportJob.isActive;

  // A missing report is the normal case for a historic race, not an error.
  const missing = state.status === "error" && isNotFound(state.error);

  return (
    <Panel as="section" className="p-[22px]" id="report">
      <SectionHeading>Race Report</SectionHeading>

      {genError ? (
        <ErrorState title="COULD NOT GENERATE" body={genError} onRetry={onGenerate} />
      ) : null}

      {missing ? (
        <EmptyState
          title="No report yet"
          body={`Reports for historic races are written on request. Generating one for the ${eventName} runs the analytics and asks the model to write it up — then it is stored permanently.`}
          action={
            <Button onClick={onGenerate} disabled={generating}>
              {generating ? "Generating…" : "Generate race report"}
            </Button>
          }
        />
      ) : (
        <AsyncBoundary state={state} loading={<SkeletonRows count={5} />}>
          {(report) => (
            <div>
              <div className="mb-4 text-sm text-ink-ghost">
                {report.trigger === "automatic" ? "AUTO-GENERATED" : "ON REQUEST"} ·{" "}
                {report.model} · {formatTimestamp(report.generated_at)}
              </div>
              <div className="flex flex-col gap-5">
                {report.sections.slice(0, 2).map((section) => (
                  <div key={section.heading}>
                    <div className="gm-label mb-2">{section.heading}</div>
                    <p className="m-0 whitespace-pre-line text-base leading-[1.7] text-ink-muted text-pretty">
                      {section.body}
                    </p>
                  </div>
                ))}
              </div>
              <div className="mt-6">
                <Link href={`/reports/${report.id}`}>
                  <Button variant="quiet">READ FULL REPORT</Button>
                </Link>
              </div>
            </div>
          )}
        </AsyncBoundary>
      )}

      <LoadingPit
        active={(reportJob.isActive || reportJob.isFailed) && !dismissed}
        stage={reportJob.stage}
        stageIndex={reportJob.stageIndex}
        elapsedSeconds={reportJob.elapsedSeconds}
        failed={reportJob.isFailed}
        overdue={reportJob.isOverdue}
        error={reportJob.error}
        log={reportJob.log}
        onRetry={onGenerate}
        onDismiss={() =>
          reportJob.isFailed ? setReportJobId(null) : setDismissed(true)
        }
      />
    </Panel>
  );
}
