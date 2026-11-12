import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import type { Signals } from "../lib/insights";

const WCAG_22_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const SIGNALS: Signals = {
  pieces: 3,
  reviewed: 3,
  top_rules: [
    { rule_id: "R-TERM-03", findings: 4 },
    { rule_id: "R-CLAIM-01", findings: 2 },
  ],
  override_rate_by_rule: {
    "R-TERM-03": {
      findings: 4,
      overridden: 2,
      rate: 0.5,
      may_be_unclear: true,
    },
    "R-CLAIM-01": {
      findings: 2,
      overridden: 0,
      rate: 0,
      may_be_unclear: false,
    },
  },
  vote_split_by_rule: { "R-CLAIM-01": { voted: 2, split: 1, rate: 0.5 } },
  findings_by_day: [{ day: "2026-11-07", findings: 6 }],
  findings_by_check: { terminology: 4, claims: 2 },
  creator_signals: [],
  gaps: [
    {
      id: "g1",
      review_id: "r1",
      check: "tone",
      text: "Too breezy",
      explanation: "No rule covers slang.",
      created_at: "2026-11-07T10:00:00Z",
    },
  ],
  unavailable: [],
};

async function signedInAs(page: Page, role: string) {
  await page.route("**/stub-api/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "u1",
        email: `${role}@tarnhollow.example`,
        name: `Test ${role}`,
        role,
        tag: null,
      },
    }),
  );
}

async function noViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(WCAG_22_AA)
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test.describe("insights", () => {
  test.beforeEach(async ({ page }) => {
    await signedInAs(page, "manager");
    await page.route("**/stub-api/governance/spot-checks", (route) =>
      route.fulfill({
        json: [{ content_id: "cnt-demo-case-study", review_id: "r9" }],
      }),
    );
  });

  test("flags a rule with a high override rate", async ({ page }) => {
    await page.route("**/stub-api/insights/signals*", (route) =>
      route.fulfill({ json: SIGNALS }),
    );
    await page.goto("/insights");

    const row = page.getByRole("row", { name: /R-TERM-03/ });
    await expect(row).toContainText("50%");
    await expect(row).toContainText("May be unclear");
    await expect(
      page.getByRole("row", { name: /R-CLAIM-01/ }),
    ).not.toContainText("May be unclear");
    await expect(page.locator("main")).toContainText("Too breezy");
    await expect(
      page.getByRole("link", { name: "cnt-demo-case-study" }),
    ).toHaveAttribute("href", "/content/cnt-demo-case-study");
    await noViolations(page);
  });

  test("filters by channel on the server", async ({ page }) => {
    const seen: URL[] = [];
    await page.route("**/stub-api/insights/signals*", (route) => {
      seen.push(new URL(route.request().url()));
      return route.fulfill({ json: SIGNALS });
    });
    await page.goto("/insights");
    await expect(page.locator("main")).toContainText("3 of 3 pieces");

    await page.getByLabel("Channel").selectOption("linkedin");

    await expect
      .poll(() => seen.at(-1)?.searchParams.get("channel"))
      .toBe("linkedin");
  });
});

test.describe("memory graph", () => {
  test("draws a fact with its claims and content", async ({ page }) => {
    await signedInAs(page, "admin");
    await page.route("**/stub-api/admin/facts", (route) =>
      route.fulfill({
        json: [
          {
            id: "F-002",
            statement: "Onboarding is 30% faster.",
            value: "30%",
            source_doc: "Study",
            owner: "Insights",
            valid_until: null,
            data_class: "public",
            version: 1,
          },
        ],
      }),
    );
    await page.route("**/stub-api/memory/graph*", (route) =>
      route.fulfill({
        json: {
          nodes: [
            { id: "F-002", type: "Fact", label: "F-002" },
            { id: "claim-1", type: "Claim", label: "Cut onboarding time" },
            { id: "c1", type: "Content", label: "Agency blog" },
          ],
          edges: [
            { source: "claim-1", target: "F-002", type: "CITES" },
            { source: "c1", target: "claim-1", type: "CONTAINS" },
          ],
        },
      }),
    );
    await page.goto("/graph");

    await expect(page.getByRole("heading", { name: "Approved fact" })).toBeVisible();
    await expect(page.locator("main")).toContainText("Cut onboarding time");
    await expect(
      page.getByRole("link", { name: "Agency blog" }),
    ).toHaveAttribute("href", "/content/c1");
    await noViolations(page);
  });
});
