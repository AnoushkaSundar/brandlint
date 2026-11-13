import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const USERS = {
  admin: { id: "u-admin", email: "ada@acme.example", name: "Ada", role: "admin", tag: null },
  reviewer: { id: "u-rev", email: "lena@acme.example", name: "Lena", role: "reviewer", tag: null },
};

const RUN = {
  id: "run-1",
  state: "done",
  result: "fail",
  reasons: ["1 finding blocks this run.", "docs/a.md:3 Retired product name (R-TERM-02, high)"],
  url: "https://app.example/ci/runs/run-1",
  policy: { severity_threshold: "medium", fail_on_unsure: true },
  files: [
    {
      path: "docs/a.md",
      content_id: "c1",
      review_id: "r1",
      state: "done",
      findings: [
        {
          id: "f1",
          rule_id: "R-TERM-02",
          severity: "high",
          verdict: "VIOLATION",
          status: "open",
          span: "Tarnhollow Onramp",
          line: 3,
          title: "Retired product name",
          url: "https://app.example/ci/runs/run-1#finding-f1",
          blocking: true,
        },
      ],
    },
  ],
};

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function signIn(page: Page, who: keyof typeof USERS) {
  await page.route("**/stub-api/auth/me", (route) => route.fulfill({ json: USERS[who] }));
  await page.route("**/stub-api/orgs/current", (route) => route.fulfill({ status: 404, json: { detail: "no" } }));
  await page.route("**/stub-api/content*", (route) => route.fulfill({ json: [] }));
}

async function noViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test("an admin creates a token and sees it once", async ({ page }) => {
  await signIn(page, "admin");
  const tokens: object[] = [];
  await page.route("**/stub-api/ci/policy", (route) =>
    route.fulfill({ json: { severity_threshold: "medium", fail_on_unsure: true, ignore_rules: [], max_waiting_minutes: 15 } }),
  );
  await page.route("**/stub-api/ci/tokens", async (route) => {
    if (route.request().method() === "POST") {
      const made = { id: "t1", name: "GitHub Action", prefix: "bl_abcde", created_at: "2026-11-13T10:00:00Z", last_used_at: null, expires_at: null, revoked_at: null };
      tokens.push(made);
      return route.fulfill({ status: 201, json: { ...made, token: "bl_abcdefSECRETsecret" } });
    }
    return route.fulfill({ json: tokens });
  });
  await page.goto("/ci/settings");
  await page.getByLabel("Name").fill("GitHub Action");
  await page.getByRole("button", { name: "Create token" }).click();
  await expect(page.getByText("bl_abcdefSECRETsecret")).toBeVisible();
  await expect(page.getByText(/shown once/)).toBeVisible();
  await noViolations(page);

  await page.getByRole("button", { name: "I've copied it" }).click();
  await expect(page.getByText("bl_abcdefSECRETsecret")).toHaveCount(0);
  await expect(page.getByRole("cell", { name: "bl_abcde" })).toBeVisible(); // only the prefix is listed
});

test("the run page shows a run and its finding links to the review screen", async ({ page }) => {
  await signIn(page, "reviewer");
  await page.route("**/stub-api/ci/runs/run-1", (route) => route.fulfill({ json: RUN }));
  await page.goto("/ci/runs/run-1#finding-f1");
  await expect(page.getByRole("status").filter({ hasText: "Failed" })).toBeVisible();
  const finding = page.locator("#finding-f1");
  await expect(finding).toContainText("Retired product name");
  await expect(finding).toContainText("Blocks the run");
  await expect(finding.getByRole("link", { name: /review screen/ })).toHaveAttribute(
    "href",
    "/content/c1/review?finding=f1",
  );
  await noViolations(page);
});

test("another workspace's run is a not-found page, with nothing from it", async ({ page }) => {
  await signIn(page, "reviewer");
  await page.route("**/stub-api/ci/runs/run-x", (route) => route.fulfill({ status: 404, json: { detail: "Run not found" } }));
  await page.goto("/ci/runs/run-x");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Run not found");
  await expect(page.getByText("Retired product name")).toHaveCount(0);
});

test("the runs list, and the CI filter on the content list", async ({ page }) => {
  await signIn(page, "reviewer");
  await page.route("**/stub-api/ci/runs", (route) =>
    route.fulfill({ json: [{ id: "run-1", repo: "acme/site", pr: 7, sha: "abc", state: "done", result: "fail", created_at: "2026-11-13T10:00:00Z", finished_at: null, files: 2 }] }),
  );
  await page.goto("/ci/runs");
  await expect(page.getByRole("cell", { name: "acme/site", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /Open the run for acme\/site/ })).toHaveAttribute("href", "/ci/runs/run-1");
  await noViolations(page);

  const asked: string[] = [];
  await page.route("**/stub-api/content?source=ci", (route) => {
    asked.push(route.request().url());
    return route.fulfill({ json: [] });
  });
  await page.goto("/content");
  await page.getByLabel("Show").selectOption("ci");
  await expect.poll(() => asked.length).toBeGreaterThan(0);
});

test("the insights view shows CI activity in counts, and nothing when there is none to read", async ({ page }) => {
  await signIn(page, "admin");
  await page.route("**/stub-api/insights/signals*", (route) =>
    route.fulfill({ json: { pieces: 0, reviewed: 0, top_rules: [], override_rate_by_rule: {}, vote_split_by_rule: {}, findings_by_day: [], findings_by_check: {}, creator_signals: [], gaps: [], unavailable: [] } }),
  );
  await page.route("**/stub-api/governance/spot-checks", (route) => route.fulfill({ json: [] }));
  await page.route("**/stub-api/insights/ci", (route) =>
    route.fulfill({
      json: {
        runs_30d: 12,
        runs_7d: 5,
        by_result: { pass: 7, fail: 3, error: 1, running: 1 },
        average_seconds: 41.5,
        failure_reasons: [{ reason: "The review took too long, so the run can't say whether this passes.", count: 1 }],
        tokens: [{ name: "GitHub Action", prefix: "bl_abcde", runs_7d: 5, last_used_at: null, revoked: false }],
      },
    }),
  );
  await page.goto("/insights");
  const card = page.getByRole("region", { name: "CI runs" });
  await expect(card).toContainText("5 in the last 7 days, 12 in 30");
  await expect(card).toContainText("7 passed, 3 failed");
  await noViolations(page);
});
