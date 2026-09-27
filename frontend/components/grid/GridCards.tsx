"use client";

import Image from "next/image";
import { useState } from "react";
import type { CurrentGrid, GridDriver } from "@/lib/api/types";
import { DRIVER_BIOS, TEAM_INFO, driverName, type GridTeam } from "@/lib/grid";
import { teamColor, teamLogoSrc } from "@/lib/teams";
import { formatTimestamp } from "@/lib/format";
import { TeamName } from "@/components/ui/TeamName";
import { Panel } from "@/components/ui/primitives";

/** The livery colour: the one the source sent, else our own for the team. */
function liveryColour(team: Pick<GridTeam, "colour" | "key">): string {
  return team.colour ?? teamColor(team.key);
}

/** Which race the line-up was read from, and whether it may be out of date. */
export function GridSource({ grid }: { grid: CurrentGrid }) {
  return (
    <p className="m-0 mt-1.5 text-sm text-ink-dim">
      As raced at {grid.race_location} on {grid.race_date}.
      {grid.is_stale && grid.fetched_at
        ? ` The source is unreachable, so this is the line-up from ${formatTimestamp(grid.fetched_at)}.`
        : ""}
    </p>
  );
}

/**
 * The official headshot, on the team's colour. If the image cannot be loaded
 * the driver's code stands in, so a broken link never leaves an empty box.
 */
function Headshot({ driver, colour }: { driver: GridDriver; colour: string }) {
  const [failed, setFailed] = useState(false);
  const showPhoto = driver.headshot_url !== null && !failed;
  return (
    <div
      className="relative h-28 w-28 shrink-0 overflow-hidden rounded-sm"
      style={{ background: `linear-gradient(160deg, ${colour}55, ${colour}10 70%)` }}
    >
      {showPhoto ? (
        <Image
          src={driver.headshot_url!}
          alt={`${driverName(driver)}, official headshot`}
          fill
          sizes="112px"
          unoptimized
          className="object-cover object-top"
          onError={() => setFailed(true)}
        />
      ) : (
        <span
          aria-hidden="true"
          className="absolute inset-0 flex items-center justify-center font-display text-3xl font-bold text-ink"
        >
          {driver.code}
        </span>
      )}
    </div>
  );
}

export function DriverCard({ driver, team }: { driver: GridDriver; team: GridTeam }) {
  const colour = liveryColour(team);
  const bio = DRIVER_BIOS[driver.code];
  return (
    <Panel as="article" className="relative flex animate-rise gap-4 p-5">
      <span
        aria-hidden="true"
        className="absolute bottom-0 left-0 top-0 w-[3px]"
        style={{ backgroundColor: colour }}
      />
      <Headshot driver={driver} colour={colour} />
      <div className="min-w-0">
        <div className="gm-label">
          #{driver.number} · {driver.code}
        </div>
        <h2 className="m-0 mt-1 font-display text-xl font-semibold uppercase leading-tight tracking-[0.02em]">
          {driverName(driver)}
        </h2>
        <TeamName name={driver.team_name} className="mt-1 text-sm text-ink-dim" />
        {bio ? (
          <p className="m-0 mt-3 text-sm leading-relaxed text-ink-muted text-pretty">{bio}</p>
        ) : null}
      </div>
    </Panel>
  );
}

export function TeamCard({ team }: { team: GridTeam }) {
  const colour = liveryColour(team);
  const info = team.key ? TEAM_INFO[team.key] : undefined;
  const logo = teamLogoSrc(team.key);
  return (
    <Panel as="article" className="relative flex animate-rise flex-col gap-4 p-5">
      <span
        aria-hidden="true"
        className="absolute bottom-0 left-0 top-0 w-[3px]"
        style={{ backgroundColor: colour }}
      />
      <div className="flex items-center gap-4">
        <div
          className="flex h-16 w-16 shrink-0 items-center justify-center rounded-sm"
          style={{ background: `linear-gradient(160deg, ${colour}40, ${colour}10 70%)` }}
        >
          {logo ? (
            <Image
              src={logo}
              alt={`${team.name} logo`}
              width={56}
              height={56}
              unoptimized
              className="h-14 w-14 object-contain"
            />
          ) : (
            <span aria-hidden="true" className="h-10 w-1.5 rounded-sm" style={{ backgroundColor: colour }} />
          )}
        </div>
        <div className="min-w-0">
          <div className="gm-label">{team.name}</div>
          <h2 className="m-0 mt-1 font-display text-xl font-semibold uppercase leading-tight tracking-[0.02em]">
            {info?.fullName ?? team.name}
          </h2>
        </div>
      </div>
      {info ? (
        <p className="m-0 text-sm leading-relaxed text-ink-muted text-pretty">{info.bio}</p>
      ) : null}
      <div className="mt-auto border-t border-line-subtle pt-3 text-sm text-ink-dim">
        <span className="gm-label mr-2">Drivers</span>
        {team.drivers.map((d) => `${driverName(d)} #${d.number}`).join(" · ")}
      </div>
    </Panel>
  );
}
