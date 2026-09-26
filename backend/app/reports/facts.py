"""The facts a race report may use, computed before the model sees anything.

Built from the same analytics the race pages serve (`analytics/race_stats.py`),
so the report and the page can never disagree. The model receives these as
compact text rather than JSON (the free tier allows 8K tokens a minute, and a
full classification in JSON would use most of it) and writes prose over them.
It computes nothing: gains, stop counts and the quickest stops are ranked
here.

The "Key Numbers" section is written entirely by this module. The plan asks
for deterministic values there, and the cheapest way to guarantee a number is
right is not to let the model write it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.api.schemas.race import (
    ClassificationRow,
    DriverStrategy,
    PositionChange,
    RaceControlEventOut,
    RaceDetail,
    RaceStats,
)

#: Strategies for the top finishers only; the tail rarely matters and costs tokens.
STRATEGY_DRIVERS = 10
TOP_MOVERS = 3
QUICKEST_STOPS = 3
MAX_RACE_CONTROL = 8
#: Race-control messages worth a report. Blue flags and track limits are noise.
#: Whole words: "CHEQUERED FLAG" contains "RED FLAG" as a substring.
NOTABLE_EVENTS = re.compile(
    r"\b(SAFETY CAR|VSC|VIRTUAL SAFETY CAR|RED FLAG|PENALTY|DISQUALIFIED)\b"
)
#: Statuses that mean the car was classified at the flag.
FINISHED_STATUSES = ("finished", "lapped")


class IncompleteRaceError(ValueError):
    """The stored race lacks what a report needs. The message is user-facing."""


@dataclass(frozen=True, slots=True)
class ReportFacts:
    race: RaceDetail
    stats: RaceStats

    @property
    def classification(self) -> list[ClassificationRow]:
        return sorted(self.stats.classification, key=lambda row: row.position)

    def retirements(self) -> list[ClassificationRow]:
        return [
            row
            for row in self.classification
            if not row.status.lower().startswith(FINISHED_STATUSES)
            and not row.status.startswith("+")
        ]

    def text(self) -> str:
        """Everything the model may say, one fact per line."""
        sections = [
            self._overview(),
            self._classification(),
            self._movers(),
            self._retirements(),
            self._strategies(),
            self._pit_stops(),
            self._race_control(),
        ]
        return "\n\n".join(s for s in sections if s)

    def key_numbers(self) -> str:
        race = self.race
        parts = [f"Laps: {race.total_laps}" if race.total_laps else None]
        if race.winner_name:
            parts.append(f"Winner: {race.winner_name}")
        if race.fastest_lap_time and race.fastest_lap_driver:
            parts.append(f"Fastest lap: {race.fastest_lap_time} ({race.fastest_lap_driver})")
        if race.safety_car_periods is not None:
            parts.append(f"Safety car periods: {race.safety_car_periods}")
        parts.append(f"Pit stops: {len(self.stats.pit_stops)}")
        gains = self._gains()
        if gains and gains[0].positions_gained > 0:
            best = gains[0]
            parts.append(f"Biggest gain: {best.driver_name} (+{best.positions_gained})")
        finishers = len(self.classification) - len(self.retirements())
        parts.append(f"Classified finishers: {finishers} of {len(self.classification)}")
        return " · ".join(p for p in parts if p)

    # -- sections of the fact sheet ---------------------------------------

    def _overview(self) -> str:
        race = self.race
        lines = [
            f"RACE: {race.season} {race.event_name}, round {race.round}, "
            f"{race.circuit_name}, {race.event_date}."
        ]
        if race.total_laps:
            lines.append(f"Laps: {race.total_laps}.")
        if race.winner_name:
            lines.append(f"Winner: {race.winner_name}.")
        if race.fastest_lap_time and race.fastest_lap_driver:
            lines.append(f"Fastest lap: {race.fastest_lap_driver}, {race.fastest_lap_time}.")
        if race.safety_car_periods is not None:
            lines.append(f"Safety car periods: {race.safety_car_periods}.")
        return " ".join(lines)

    def _classification(self) -> str:
        lines = ["CLASSIFICATION (position. driver, team, grid, points, status, best lap, stops):"]
        for row in self.classification:
            grid = f"grid {row.grid_position}" if row.grid_position else "pit lane start"
            best = f"best {row.best_lap_time}" if row.best_lap_time else "no timed lap"
            stops = f"{row.pit_stop_count} stops" if row.pit_stop_count is not None else ""
            points = f"{row.points:g} pts"
            fields = [row.driver_name, row.constructor_name, grid, points, row.status, best, stops]
            lines.append(f"{row.position}. " + ", ".join(f for f in fields if f))
        return "\n".join(lines)

    def _gains(self) -> list[PositionChange]:
        return sorted(self.stats.position_changes, key=lambda c: -c.positions_gained)

    def _movers(self) -> str:
        changes = self._gains()
        gains = [c for c in changes if c.positions_gained > 0][:TOP_MOVERS]
        losses = [c for c in reversed(changes) if c.positions_gained < 0][:TOP_MOVERS]
        lines = []
        if gains:
            lines.append(
                "BIGGEST GAINS FROM THE GRID: "
                + "; ".join(
                    f"{c.driver_name} +{c.positions_gained} (grid {c.grid_position} to "
                    f"{c.finish_position})"
                    for c in gains
                )
            )
        if losses:
            lines.append(
                "BIGGEST LOSSES FROM THE GRID: "
                + "; ".join(
                    f"{c.driver_name} {c.positions_gained} (grid {c.grid_position} to "
                    f"{c.finish_position})"
                    for c in losses
                )
            )
        return "\n".join(lines)

    def _retirements(self) -> str:
        out = self.retirements()
        if not out:
            return "RETIREMENTS: none."
        return "RETIREMENTS: " + "; ".join(f"{r.driver_name} ({r.status})" for r in out)

    def _strategies(self) -> str:
        order = {row.driver_code: row.position for row in self.classification}
        top = sorted(self.stats.strategies, key=lambda s: order.get(s.driver_code, 99))
        lines = [_strategy_line(s) for s in top[:STRATEGY_DRIVERS] if s.stints]
        if not lines:
            return ""
        heading = "TYRE STRATEGY (stops; stints as compound and laps), top finishers:"
        return heading + "\n" + "\n".join(lines)

    def _pit_stops(self) -> str:
        stops = self.stats.pit_stops
        if not stops:
            return "PIT STOPS: none recorded."
        quickest = sorted(stops, key=lambda s: s.duration_seconds)[:QUICKEST_STOPS]
        listed = "; ".join(
            f"{s.driver_name} {s.duration_seconds:.3f} s on lap {s.lap}" for s in quickest
        )
        return (
            f"PIT STOPS: {len(stops)} in total. Quickest pit-lane times (entry to exit): {listed}."
        )

    def _race_control(self) -> str:
        notable = [e for e in self.stats.race_control if _is_notable(e)][:MAX_RACE_CONTROL]
        if not notable:
            return ""
        lines = [f"lap {e.lap}: {e.message}" if e.lap else e.message for e in notable]
        return "RACE CONTROL:\n" + "\n".join(lines)


def _strategy_line(strategy: DriverStrategy) -> str:
    # The stop count is stated, not left to be inferred: live, the model read
    # three stints as a "three-stop" race.
    stints = ", ".join(f"{s.compound} {s.start_lap}-{s.end_lap}" for s in strategy.stints)
    stops = len(strategy.stints) - 1
    return f"{strategy.driver_name} ({stops} {'stop' if stops == 1 else 'stops'}): {stints}"


def _is_notable(event: RaceControlEventOut) -> bool:
    return NOTABLE_EVENTS.search(event.message.upper()) is not None


def build_facts(race: RaceDetail | None, stats: RaceStats | None) -> ReportFacts:
    """The facts, or IncompleteRaceError saying what is missing."""
    if race is None or stats is None:
        raise IncompleteRaceError("The race data is not stored.")
    if not stats.classification:
        raise IncompleteRaceError("The race has no classification yet.")
    if not race.winner_name:
        raise IncompleteRaceError("The race has no winner recorded yet.")
    return ReportFacts(race, stats)
