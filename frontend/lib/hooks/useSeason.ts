"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * The season the dashboard and calendar show. Remembered locally, as the
 * frontend plan asks for "selected season" alongside sound and theme.
 *
 * It only scopes browsing. The chat never depends on it — the agent works out
 * the season from the question itself.
 */

const STORAGE_KEY = "gm.season";

/** FastF1 has full timing data from 2018 onwards. Earlier seasons cannot be fetched. */
export const FIRST_SEASON = 2018;

export function currentSeason(): number {
  return new Date().getFullYear();
}

/** Newest first, from the current season back to the first one with timing data. */
export function availableSeasons(): number[] {
  const seasons: number[] = [];
  for (let year = currentSeason(); year >= FIRST_SEASON; year--) seasons.push(year);
  return seasons;
}

export function isValidSeason(value: number): boolean {
  return Number.isInteger(value) && value >= FIRST_SEASON && value <= currentSeason();
}

const listeners = new Set<() => void>();

/** Used when storage is blocked, so the picker still works for this visit. */
let memorySeason: number | null = null;

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function getSnapshot(): number {
  try {
    const stored = Number(window.localStorage.getItem(STORAGE_KEY));
    // Storage is user-editable, so a stored value is only trusted if it is a
    // season we can actually show.
    return isValidSeason(stored) ? stored : currentSeason();
  } catch {
    return memorySeason ?? currentSeason();
  }
}

export function useSeason(): [number, (season: number) => void] {
  const season = useSyncExternalStore(subscribe, getSnapshot, currentSeason);

  const setSeason = useCallback((next: number) => {
    if (!isValidSeason(next)) return;
    memorySeason = next;
    try {
      window.localStorage.setItem(STORAGE_KEY, String(next));
    } catch {
      // Preference just will not persist across visits.
    }
    for (const listener of listeners) listener();
  }, []);

  return [season, setSeason];
}
