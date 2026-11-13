import { defineConfig, devices } from "@playwright/test";

// Port 3100 keeps these runs away from a dev server on 3000.
const PORT = 3100;
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Tests the production build, because the dev overlay skews accessibility scans.
  webServer: {
    command: `npm run build && npm run start -- -p ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    // A same-origin path that the tests stub, so they run without the API.
    env: {
      NEXT_PUBLIC_API_URL: `${BASE_URL}/stub-api`,
      // The CI pages are tested with the integration on.
      NEXT_PUBLIC_CI_ENABLED: "true",
    },
  },
});
