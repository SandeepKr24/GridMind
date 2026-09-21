"use client";

import { useCallback, useRef, useSyncExternalStore } from "react";

const STORAGE_KEY = "gm.sound";

/**
 * Sound preference lives in localStorage, which is an external store — so it is
 * read through useSyncExternalStore rather than an effect that calls setState.
 * That keeps the server render and the first client render consistent, and
 * avoids a cascading re-render on mount.
 */

const soundListeners = new Set<() => void>();

function emitSoundChange() {
  for (const listener of soundListeners) listener();
}

function subscribeSound(onChange: () => void): () => void {
  soundListeners.add(onChange);
  // Another tab toggling the preference should be reflected here too.
  window.addEventListener("storage", onChange);
  return () => {
    soundListeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function getSoundSnapshot(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    // Private mode or blocked storage. Muted is the safe default.
    return false;
  }
}

/** Server render has no storage, and muted is the correct default anyway. */
function getSoundServerSnapshot(): boolean {
  return false;
}

export function useSound() {
  const enabled = useSyncExternalStore(
    subscribeSound,
    getSoundSnapshot,
    getSoundServerSnapshot
  );
  const ctxRef = useRef<AudioContext | null>(null);

  const beep = useCallback(
    (frequency: number, duration = 0.14, peakGain = 0.12) => {
      if (!enabled) return;
      try {
        const Ctor =
          window.AudioContext ??
          (window as unknown as { webkitAudioContext?: typeof AudioContext })
            .webkitAudioContext;
        if (!Ctor) return;

        // Created lazily on first play, so a beep only ever follows a user
        // action — which is what browser autoplay policies require.
        const ctx = ctxRef.current ?? new Ctor();
        ctxRef.current = ctx;
        if (ctx.state === "suspended") void ctx.resume();

        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        const now = ctx.currentTime;

        osc.type = "sine";
        osc.frequency.value = frequency;
        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.exponentialRampToValueAtTime(peakGain, now + 0.012);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now);
        osc.stop(now + duration + 0.03);
      } catch {
        // Audio is never required to understand loading state, so failing is fine.
      }
    },
    [enabled]
  );

  const toggle = useCallback(() => {
    const next = !getSoundSnapshot();
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      // Preference just will not persist. Not worth surfacing.
    }
    emitSoundChange();
  }, []);

  /** Rising tone per light, with a brighter tone when the sequence completes. */
  const beepForStage = useCallback(
    (stageIndex: number, isFinal: boolean) => {
      if (isFinal) beep(990, 0.3, 0.16);
      else beep(600 + stageIndex * 70, 0.1);
    },
    [beep]
  );

  return { enabled, toggle, beep, beepForStage };
}

/* ---------- Reduced motion ---------- */

const MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function subscribeMotion(onChange: () => void): () => void {
  const query = window.matchMedia(MOTION_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function getMotionSnapshot(): boolean {
  return window.matchMedia(MOTION_QUERY).matches;
}

/**
 * On the server we cannot know the preference. Assuming "not reduced" matches
 * the CSS fallback, and the global reduced-motion media query in globals.css
 * still suppresses animation for those users regardless of what JS thinks.
 */
function getMotionServerSnapshot(): boolean {
  return false;
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeMotion,
    getMotionSnapshot,
    getMotionServerSnapshot
  );
}
