"use client";

import Link from "next/link";
import { useCallback } from "react";
import { useParams } from "next/navigation";
import { getReport } from "@/lib/api/reports";
import { useAsync } from "@/lib/hooks/useAsync";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import {
  Button,
  EmptyState,
  Panel,
  SkeletonRows,
} from "@/components/ui/primitives";
import type { Report } from "@/lib/api/types";

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const reportId = params.id;

  const load = useCallback(() => getReport(reportId), [reportId]);
  const state = useAsync<Report>(load, [reportId]);

  return (
    <AsyncBoundary state={state} loading={<SkeletonRows count={8} />}>
      {(report) => (
        <article className="mx-auto flex max-w-[860px] animate-fade flex-col gap-6">
          <header className="border-b border-line pb-6">
            <div className="font-mono text-[11px] tracking-[0.2em] text-accent">
              {report.report_type.toUpperCase().replace(/_/g, " ")}
            </div>
            <h1 className="m-0 mt-3 font-display text-[clamp(34px,6vw,64px)] font-bold uppercase leading-[0.95]">
              {report.event_name}
            </h1>
            <div className="mt-3 flex flex-wrap gap-4 font-mono text-[11px] text-ink-ghost">
              <span>{report.season} SEASON</span>
              <span>
                {report.trigger === "automatic" ? "AUTO-GENERATED" : "ON REQUEST"}
              </span>
              <span>{report.model}</span>
              <span>{report.generated_at}</span>
            </div>
          </header>

          {report.sections.length === 0 ? (
            <EmptyState
              title="Empty report"
              body="This report was stored without any sections. That is a backend problem rather than a display one."
            />
          ) : (
            <div className="flex flex-col gap-8">
              {report.sections.map((section) => (
                <section key={section.heading}>
                  <h2 className="gm-heading mb-3 text-base">{section.heading}</h2>
                  <p className="m-0 text-[16px] leading-[1.75] text-ink-muted text-pretty">
                    {section.body}
                  </p>
                </section>
              ))}
            </div>
          )}

          <Panel className="mt-2 flex flex-wrap items-center justify-between gap-4 p-5">
            <div className="text-sm text-ink-dim">
              Every number in this report came from stored timing data.
            </div>
            <div className="flex gap-2.5">
              <Link href={`/races/${report.race_id}`}>
                <Button variant="quiet">RACE DATA</Button>
              </Link>
              <Link href="/chat">
                <Button variant="quiet">ASK ABOUT THIS RACE</Button>
              </Link>
            </div>
          </Panel>
        </article>
      )}
    </AsyncBoundary>
  );
}
