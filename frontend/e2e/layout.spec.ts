import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * Responsive layout: every page at phone, tablet and desktop widths must fit
 * the viewport without sideways scrolling. Wide tables are allowed to scroll
 * inside their own container — the page itself must not.
 */

const WIDTHS = [320, 375, 768, 1440];

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth
  );
  expect(overflow, "page is wider than the viewport").toBeLessThanOrEqual(0);
}

const PAGES: { name: string; path: string; ready: string; raceState?: "ingested" | "available"; act?: (page: Page) => Promise<void> }[] = [
  { name: "dashboard", path: "/", ready: "Latest Podium" },
  { name: "races", path: "/races", ready: "Italian Grand Prix" },
  { name: "race-detail", path: "/races/2025-14", ready: "Classification" },
  { name: "report", path: "/reports/r1", ready: "RACE STORY" },
  {
    name: "chat",
    path: "/chat",
    ready: "Ask the Race Analyst",
    act: async (page) => {
      await page.getByLabel("Ask about a Formula 1 race").fill("Who gained the most at Monza?");
      await page.getByRole("button", { name: "SEND" }).click();
      await page.getByText("GAINED by DRIVER").waitFor();
    },
  },
  {
    name: "loading-pit",
    path: "/races/2025-14?job=j1",
    ready: "Fetching timing data...",
    raceState: "available",
  },
];

for (const width of WIDTHS) {
  for (const p of PAGES) {
    test(`${p.name} fits at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      // Entrance animations would otherwise be caught mid-fade in screenshots.
      await page.emulateMedia({ reducedMotion: "reduce" });
      await mockApi(page, { raceState: p.raceState });

      await page.goto(p.path);
      await page.getByText(p.ready, { exact: true }).first().waitFor();
      if (p.act) await p.act(page);

      await expectNoHorizontalOverflow(page);
      await page.screenshot({
        path: `test-results/layout/${p.name}-${width}.png`,
        fullPage: true,
      });
    });
  }
}
