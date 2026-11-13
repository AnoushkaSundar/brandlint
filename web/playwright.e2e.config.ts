import { defineConfig, devices } from "@playwright/test";

// The end-to-end test against a REAL stack (the web app, the API and Postgres), not stubs.
// Start the stack first: demo/run_e2e.sh does, and then runs this.
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 180_000,
  reporter: "list",
  use: { baseURL: process.env.E2E_WEB ?? "http://localhost:3100" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
