import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import type { Drafts } from "../lib/admin";
import type { Fact, Rule } from "../lib/contracts";

const WCAG_22_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

function rule(id: string, clause: string, text: string): Rule {
  return {
    id,
    version: 1,
    type: "judgment",
    text,
    clause_ref: clause,
    severity: "medium",
    channel_scope: [],
    status: "draft",
  };
}

const DRAFTS: Drafts = {
  version: 1,
  drafts: [
    rule("R-TERM-04", "§3.4", "Say 'you' to the reader."),
    rule("R-TONE-01", "§2.1", "Be warm, never pushy."),
    rule("R-TONE-04", "§2.4", "Never address the reader directly."),
  ],
  conflicts: [["R-TERM-04", "R-TONE-04"]],
};

const FACTS: Fact[] = [
  {
    id: "F-001",
    statement: "Customers onboard 30% faster.",
    value: "30%",
    source_doc: "Study 2024",
    owner: "Insights",
    valid_until: "2025-01-31",
    data_class: "public",
    version: 1,
  },
  {
    id: "F-002",
    statement: "Used by 400 teams.",
    value: "400",
    source_doc: "CRM export",
    owner: "Sales ops",
    valid_until: null,
    data_class: "public",
    version: 1,
  },
];

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

async function noViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(WCAG_22_AA)
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test.describe("rulebook", () => {
  test.beforeEach(async ({ page }) => {
    await signedInAsAdmin(page);
    await page.route("**/stub-api/admin/rulebook*", (route) =>
      route.fulfill({ status: 404, json: { detail: "No approved rules" } }),
    );
    await page.route("**/stub-api/admin/rules/drafts", (route) =>
      route.fulfill({ json: DRAFTS }),
    );
  });

  test("flags both sides of a conflict", async ({ page }) => {
    await page.goto("/brand/rulebook");

    await expect(page.locator("main")).toContainText("Contradicts R-TONE-04");
    await expect(page.locator("main")).toContainText("Contradicts R-TERM-04");
    await expect(page.locator("main")).toContainText("No approved rules yet");
    await noViolations(page);
  });

  test("approves the selected drafts and shows the server's refusal", async ({
    page,
  }) => {
    const sent: unknown[] = [];
    await page.route("**/stub-api/admin/rules/approve", (route) => {
      sent.push(route.request().postDataJSON());
      return route.fulfill({
        status: 409,
        json: { detail: "R-TERM-04 and R-TONE-04 contradict each other." },
      });
    });
    await page.goto("/brand/rulebook");

    await page.getByRole("button", { name: "Select all" }).click();
    await page.getByRole("button", { name: /Approve 3/ }).click();

    await expect(page.locator("main").getByRole("alert")).toContainText(
      "contradict",
    );
    expect(sent).toEqual([
      { rule_ids: ["R-TERM-04", "R-TONE-01", "R-TONE-04"] },
    ]);
  });

  test("uploads a guideline", async ({ page }) => {
    await page.route("**/stub-api/admin/ingest", (route) =>
      route.fulfill({
        status: 201,
        json: {
          id: "j1",
          status: "done",
          error: null,
          result: { version: 1, rules: ["a", "b", "c"], conflicts: [] },
        },
      }),
    );
    await page.goto("/brand/rulebook");

    await page.getByLabel("PDF, DOCX or text file").setInputFiles({
      name: "guidelines.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("§2.1 Be warm."),
    });
    await page.getByRole("button", { name: "Read guideline" }).click();

    await expect(page.locator("main").getByRole("status")).toContainText(
      "Read 3 rules from guidelines.txt",
    );
  });
});

test.describe("facts", () => {
  test.beforeEach(async ({ page }) => {
    await signedInAsAdmin(page);
    await page.route("**/stub-api/admin/facts", (route) =>
      route.fulfill({ json: FACTS }),
    );
  });

  test("highlights an expired fact", async ({ page }) => {
    await page.goto("/brand/facts");

    await expect(
      page.getByRole("listitem").filter({ hasText: "F-001" }),
    ).toContainText("Expired");
    await expect(
      page.getByRole("listitem").filter({ hasText: "F-002" }),
    ).not.toContainText("Expired");
    await noViolations(page);
  });

  test("shows the pieces an edit affects", async ({ page }) => {
    await page.route("**/stub-api/admin/facts/F-001", (route) =>
      route.fulfill({
        json: {
          fact: { ...FACTS[0], value: "41%", version: 2 },
          impact: [
            { content_id: "c1", state: "published", claim_text: "30% faster" },
          ],
        },
      }),
    );
    await page.goto("/brand/facts");

    await page.getByRole("button", { name: "Edit F-001" }).click();
    await page.getByLabel("Value").fill("41%");
    await page.getByRole("button", { name: "Save new version" }).click();

    const notice = page.locator("main").getByRole("status");
    await expect(notice).toContainText("1 piece cites the old wording");
    await expect(
      notice.getByRole("link", { name: "“30% faster”" }),
    ).toHaveAttribute("href", "/content/c1");
  });
});

test("terms and assets screens pass an accessibility scan", async ({
  page,
}) => {
  await signedInAsAdmin(page);
  await page.route("**/stub-api/admin/terms", (route) =>
    route.fulfill({
      json: [
        {
          id: "T-001",
          preferred: "new hire",
          banned: ["newbie"],
          rule_id: "R-TERM-03",
        },
      ],
    }),
  );
  await page.route("**/stub-api/admin/assets", (route) =>
    route.fulfill({
      json: [
        {
          id: "A-001",
          kind: "palette",
          file_ref: "",
          meta: { colours: ["#12343B"] },
        },
        {
          id: "A-002",
          kind: "logo",
          file_ref: "x.png",
          meta: { name: "logo.png" },
        },
      ],
    }),
  );

  await page.goto("/brand/terms");
  await expect(page.locator("main")).toContainText("newbie");
  await noViolations(page);

  await page.goto("/brand/assets");
  await expect(page.locator("main")).toContainText("#12343B");
  await noViolations(page);
});
