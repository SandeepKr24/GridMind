"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useReducedMotion, useSound } from "@/lib/hooks/useSound";
import { useSeason } from "@/lib/hooks/useSeason";

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
  setSeason: (season: number) => void;
}

const SettingsContext = createContext<Settings | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const { enabled, toggle, beepForStage } = useSound();
  const reducedMotion = useReducedMotion();
  const [season, setSeason] = useSeason();

  const value = useMemo<Settings>(
    () => ({
      soundEnabled: enabled,
      toggleSound: toggle,
      beepForStage,
      reducedMotion,
      season,
      setSeason,
    }),
    [enabled, toggle, beepForStage, reducedMotion, season, setSeason]
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
