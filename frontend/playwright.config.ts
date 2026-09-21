import { defineConfig, devices } from "@playwright/test";

/**
 * Browser checks. The API is answered from fixtures inside each test, so these
 * run without a backend — they exercise real layout, not real data.
 */
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: true,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
