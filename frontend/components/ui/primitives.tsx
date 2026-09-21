import type { ReactNode } from "react";
import type { IngestionState } from "@/lib/api/types";

export function Panel({
  children,
  className = "",
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article";
}) {
  return (
    <Tag className={`border border-line bg-surface-raised ${className}`}>
      {children}
    </Tag>
  );
}

export function SectionHeading({
  children,
  right,
}: {
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="mb-[18px] flex items-baseline justify-between gap-3">
      <h2 className="gm-heading text-[15px]">{children}</h2>
      {right ? <div className="font-mono text-[11px] text-ink-ghost">{right}</div> : null}
    </div>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return <div className="gm-label">{children}</div>;
}

/**
 * Ingestion-state badge. Always renders a text label alongside the colour dot —
 * no information is conveyed by colour alone.
 */
export function IngestionBadge({ state }: { state: IngestionState }) {
  const config: Record<
    IngestionState,
    { label: string; dot: string; text: string; ring: string }
  > = {
    ingested: {
      label: "INGESTED",
      dot: "bg-status-ready",
      text: "text-status-ready",
      ring: "border-status-ready/30 bg-status-ready/10",
    },
    available: {
      label: "AVAILABLE",
      dot: "bg-status-pending",
      text: "text-status-pending",
      ring: "border-status-pending/30 bg-status-pending/10",
    },
    upcoming: {
      label: "UPCOMING",
      dot: "bg-status-idle",
      text: "text-ink-ghost",
      ring: "border-line-strong bg-surface-hover",
    },
  };

  const c = config[state];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm border px-[7px] py-[3px] font-mono text-[9px] tracking-[0.14em] ${c.ring} ${c.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} aria-hidden="true" />
      {c.label}
    </span>
  );
}

export function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="bg-surface-raised px-[22px] py-5">
      <div className="gm-label mb-2">{label}</div>
      <div className="font-display text-[40px] font-bold leading-none">{value}</div>
      <div className="mt-1.5 text-xs text-ink-dim">{sub}</div>
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  type = "button",
  disabled,
  ...rest
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "quiet";
  type?: "button" | "submit";
  disabled?: boolean;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick" | "type">) {
  const base =
    "font-display font-bold uppercase tracking-[0.14em] transition-colors disabled:cursor-not-allowed disabled:opacity-40";
  const styles = {
    primary: "bg-accent text-white hover:bg-accent-bright px-[26px] py-3.5 text-base",
    ghost:
      "border border-line-strong bg-transparent text-ink hover:border-ink hover:bg-surface-hover px-[26px] py-3.5 text-base",
    quiet:
      "border border-line-strong bg-transparent text-ink-muted hover:border-ink-dim hover:text-ink px-5 py-2.5 font-mono text-[11px] tracking-[0.12em] normal-case",
  }[variant];

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${styles}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Loading placeholder. Used while a real request is genuinely in flight. */
export function SkeletonRows({ count = 6 }: { count?: number }) {
  return (
    <div className="flex flex-col gap-2.5" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="h-3 animate-pulse-slow bg-[#171A1F]"
          style={{ width: `${92 - i * 7}%`, animationDelay: `${i * 120}ms` }}
        />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="border border-dashed border-line-strong bg-surface-raised px-6 py-12 text-center">
      <div className="font-display text-xl uppercase tracking-[0.14em] text-ink-dim">
        {title}
      </div>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-ink-ghost text-pretty">
        {body}
      </p>
      {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title,
  body,
  onRetry,
}: {
  title: string;
  body: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="border border-accent/30 bg-accent/[0.04] px-6 py-10 text-center"
    >
      <div className="font-display text-xl uppercase tracking-[0.14em] text-ink">
        {title}
      </div>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-ink-muted text-pretty">
        {body}
      </p>
      {onRetry ? (
        <div className="mt-6 flex justify-center">
          <Button variant="quiet" onClick={onRetry}>
            TRY AGAIN
          </Button>
        </div>
      ) : null}
    </div>
  );
}
