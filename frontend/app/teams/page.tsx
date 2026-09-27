"use client";

import { getGrid } from "@/lib/api/grid";
import type { CurrentGrid } from "@/lib/api/types";
import { useAsync } from "@/lib/hooks/useAsync";
import { groupTeams } from "@/lib/grid";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { GridSource, TeamCard } from "@/components/grid/GridCards";
import { SkeletonRows } from "@/components/ui/primitives";

/** Every team on the current grid, with the drivers it raced last time out. */
export default function TeamsPage() {
  const state = useAsync<CurrentGrid>(getGrid, []);

  return (
    <div className="flex flex-col gap-5">
      <AsyncBoundary state={state} loading={<SkeletonRows count={6} />}>
        {(grid) => (
          <>
            <header className="animate-fade">
              <h1 className="m-0 font-display text-[clamp(30px,4.5vw,44px)] font-bold uppercase leading-none">
                {grid.season} Teams
              </h1>
              <GridSource grid={grid} />
            </header>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(min(360px,100%),1fr))] gap-4">
              {groupTeams(grid.drivers).map((team) => (
                <TeamCard key={team.name} team={team} />
              ))}
            </div>
          </>
        )}
      </AsyncBoundary>
    </div>
  );
}
