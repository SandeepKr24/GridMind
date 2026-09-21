"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useReducedMotion, useSound } from "@/lib/hooks/useSound";

/**
 * Small global settings only — sound, motion and selected season.
 * The frontend plan is explicit about not reaching for a state library for this.
 */

interface Settings {
  soundEnabled: boolean;
  toggleSound: () => void;
  beepForStage: (stageIndex: number, isFinal: boolean) => void;
  reducedMotion: boolean;
  season: number;
}

const SettingsContext = createContext<Settings | null>(null);

/** Current F1 season. Kept here so one edit moves the whole UI. */
export const DEFAULT_SEASON = 2026;

export function SettingsProvider({ children }: { children: ReactNode }) {
  const { enabled, toggle, beepForStage } = useSound();
  const reducedMotion = useReducedMotion();

  const value = useMemo<Settings>(
    () => ({
      soundEnabled: enabled,
      toggleSound: toggle,
      beepForStage,
      reducedMotion,
      season: DEFAULT_SEASON,
    }),
    [enabled, toggle, beepForStage, reducedMotion]
  );

  return (
    <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
  );
}

export function useSettings(): Settings {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be used inside SettingsProvider");
  return ctx;
}
