"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";

const FORZA_HELPER_URL = "https://forzahelper-fh6.vercel.app/";

/** Grace period before closing, so moving between the logo and a link does not flicker. */
const CLOSE_DELAY_MS = 180;
/**
 * A tap focuses the logo (which opens the island) and then clicks it. A click
 * this soon after opening is that same tap, so it must not close it again.
 */
const JUST_OPENED_MS = 400;

function HelmetIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 15.5C3 9.7 7.5 5 13 5c4.4 0 8 3.3 8 7.5V16a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <path d="M11 12.5a3 3 0 0 1 3-3h6.6" />
      <path d="M11 12.5h10" />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l7 3v5.5c0 4.3-2.9 7.8-7 9.5-4.1-1.7-7-5.2-7-9.5V6z" />
      <path d="M12 3v18" />
      <path d="M5 11h14" />
    </svg>
  );
}

interface IslandItem {
  label: string;
  icon: ReactNode;
  href: string;
  external?: boolean;
}

const ABOVE: IslandItem[] = [
  { label: "Drivers", icon: <HelmetIcon />, href: "/drivers" },
  { label: "Teams", icon: <ShieldIcon />, href: "/teams" },
];

const BELOW: IslandItem[] = [
  {
    label: "Forza Helper",
    icon: (
      <Image src="/forzahelper.png" alt="" width={24} height={24} unoptimized className="h-6 w-6 rounded-[5px]" />
    ),
    href: FORZA_HELPER_URL,
    external: true,
  },
];

function IslandLink({
  item,
  open,
  onNavigate,
}: {
  item: IslandItem;
  open: boolean;
  onNavigate: () => void;
}) {
  const className =
    "group relative flex h-11 w-11 items-center justify-center rounded-full text-ink-muted no-underline transition-colors hover:bg-surface-hover hover:text-ink focus-visible:bg-surface-hover focus-visible:text-ink";
  const body = (
    <>
      {item.icon}
      {/* A visible name to the left, so each icon says where it goes. */}
      <span className="pointer-events-none absolute right-full mr-3 whitespace-nowrap rounded-sm border border-line-strong bg-surface-raised px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.08em] text-ink opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
        {item.label}
      </span>
    </>
  );
  // Closed items stay in the layout but cannot be reached or clicked.
  const tabIndex = open ? undefined : -1;
  if (item.external) {
    return (
      <a
        href={item.href}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`${item.label} (opens in a new tab)`}
        tabIndex={tabIndex}
        onClick={onNavigate}
        className={className}
      >
        {body}
      </a>
    );
  }
  return (
    <Link href={item.href} aria-label={item.label} tabIndex={tabIndex} onClick={onNavigate} className={className}>
      {body}
    </Link>
  );
}

/**
 * A small panel fixed to the middle of the right edge. At rest it is only the
 * GridMind logo; hovering it, focusing it or tapping it brings out the quick
 * links, above and below the logo.
 */
export function QuickIsland() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const openedAt = useRef(0);
  // Set while Escape hands focus back to the logo, so that focus does not reopen it.
  const returningFocus = useRef(false);
  const menuId = useId();

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) clearTimeout(closeTimer.current);
    closeTimer.current = null;
  }, []);

  const show = useCallback(() => {
    cancelClose();
    setOpen((wasOpen) => {
      if (!wasOpen) openedAt.current = performance.now();
      return true;
    });
  }, [cancelClose]);


  const hideSoon = useCallback(() => {
    cancelClose();
    closeTimer.current = setTimeout(() => setOpen(false), CLOSE_DELAY_MS);
  }, [cancelClose]);

  const close = useCallback(() => {
    cancelClose();
    setOpen(false);
  }, [cancelClose]);

  const toggle = useCallback(() => {
    if (!open) return show();
    if (performance.now() - openedAt.current < JUST_OPENED_MS) return;
    close();
  }, [open, show, close]);

  useEffect(() => cancelClose, [cancelClose]);

  // Escape and a tap elsewhere close it, the way a menu should.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      close();
      returningFocus.current = true;
      toggleRef.current?.focus();
      returningFocus.current = false;
    };
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open, close]);

  const group = (items: IslandItem[], position: "above" | "below") => (
    <div
      className={`absolute left-1/2 flex -translate-x-1/2 flex-col items-center gap-1 rounded-full border border-line-strong bg-surface-raised/95 p-1 shadow-[0_8px_24px_rgba(0,0,0,.45)] backdrop-blur-[10px] transition-[opacity,transform] duration-200 ${
        position === "above" ? "bottom-full mb-2" : "top-full mt-2"
      } ${
        open
          ? "visible translate-y-0 opacity-100"
          : `invisible opacity-0 ${position === "above" ? "translate-y-2" : "-translate-y-2"}`
      }`}
    >
      {items.map((item) => (
        <IslandLink key={item.href} item={item} open={open} onNavigate={close} />
      ))}
    </div>
  );

  return (
    <div
      ref={rootRef}
      className="fixed right-3 top-1/2 z-[60] -translate-y-1/2"
      // Hover is for mice; a touch is handled by the tap on the logo.
      onPointerEnter={(event) => event.pointerType === "mouse" && show()}
      onPointerLeave={(event) => event.pointerType === "mouse" && hideSoon()}
      onFocus={() => {
        if (!returningFocus.current) show();
      }}
      onBlur={(event) => {
        if (!rootRef.current?.contains(event.relatedTarget as Node | null)) hideSoon();
      }}
    >
      <nav id={menuId} aria-label="Quick links">
        {group(ABOVE, "above")}
        {group(BELOW, "below")}
      </nav>
      <button
        ref={toggleRef}
        type="button"
        aria-label="Quick links"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={toggle}
        className={`flex h-12 w-12 items-center justify-center rounded-full border bg-surface-raised/95 shadow-[0_8px_24px_rgba(0,0,0,.45)] backdrop-blur-[10px] transition-colors ${
          open ? "border-accent" : "border-line-strong hover:border-ink-ghost"
        }`}
      >
        <Image src="/icon.svg" alt="" width={28} height={28} unoptimized />
      </button>
    </div>
  );
}
