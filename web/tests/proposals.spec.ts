import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import type { Proposal } from "../lib/contracts";

const WCAG_22_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const PROPOSAL: Proposal = {
  id: "p1",
  rule_id: "R-TONE-02",
  kind: "amendment",
  current: "Do not use fear to persuade the reader.",
  suggested:
    "Do not use fear to persuade the reader. Describing a real risk is allowed.",
  evidence: { count: 4, examples: [] },
  eval: { passed: true, precision: 0.94, recall: 0.91 },
  status: "pending",
};

async function signedInAsAdmin(page: Page) {
  await page.route("**/stub-api/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "u1",
        email: "admin@tarnhollow.example",
        name: "Test admin",
        role: "admin",
        tag: null,
      },
    }),
  );
}

test.beforeEach(async ({ page }) => {
  await signedInAsAdmin(page);
  await page.route("**/stub-api/governance/proposals", (route) =>
    route.fulfill({ json: [PROPOSAL] }),
  );
});

test("shows the evidence, the change and the eval gate", async ({ page }) => {
  await page.goto("/proposals");

  const main = page.locator("main");
  await expect(main).toContainText("Based on 4 confirmed overrides");
  await expect(main).toContainText("Eval gate: passed");
  await expect(main).toContainText("precision 94%, recall 91%");
  await expect(main).toContainText("Describing a real risk is allowed.");
  const { violations } = await new AxeBuilder({ page })
    .withTags(WCAG_22_AA)
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});

test("approving sends the decision and points to the rulebook", async ({
  page,
}) => {
  const sent: unknown[] = [];
  await page.route("**/stub-api/governance/proposals/p1", (route) => {
    sent.push(route.request().postDataJSON());
    return route.fulfill({ json: [] });
  });
  await page.goto("/proposals");

  await page.getByRole("button", { name: "Approve" }).click();

  const notice = page.locator("main").getByRole("status");
  await expect(notice).toContainText("now a draft");
  await expect(
    notice.getByRole("link", { name: "Approve it in the rulebook" }),
  ).toHaveAttribute("href", "/brand/rulebook");
  await expect(page.locator("main")).toContainText("No proposals are waiting");
  expect(sent).toEqual([{ status: "approved" }]);
});

test("running the agent lists what it found", async ({ page }) => {
  await page.route("**/stub-api/governance/run", (route) =>
    route.fulfill({ json: [PROPOSAL] }),
  );
  await page.goto("/proposals");

  await page.getByRole("button", { name: "Run the governance agent" }).click();

  await expect(page.locator("main").getByRole("status")).toContainText(
    "1 proposal is waiting",
  );
});
