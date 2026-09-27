import { request } from "./client";
import type { CurrentGrid } from "./types";

/** The current grid: the drivers who started the latest race. */
export function getGrid(): Promise<CurrentGrid> {
  return request<CurrentGrid>("/api/grid");
}
