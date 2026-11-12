import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const ADMIN = {
  id: "user-admin",
  email: "ada@acme.example",
  name: "Ada",
  role: "admin",
  tag: null,
};

function workspace(kind: "demo" | "sandbox", checklist = {}) {
  return {
    id: "org-1",
    name: kind === "demo" ? "Tarnhollow" : "Acme Co",
    kind,
    expires_at:
      kind === "sandbox"
        ? new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString()
        : null,
    checklist: {
      guidelines: false,
      approved_rules: false,
      teammates: false,
      first_draft: false,
      ...checklist,
    },
  };
}

async function signInAsAdmin(page: Page, kind: "demo" | "sandbox") {
  await page.route("**/stub-api/auth/me", (route) =>
    route.fulfill({ json: ADMIN }),
  );
  await page.route("**/stub-api/orgs/current", (route) =>
    route.fulfill({ json: workspace(kind) }),
  );
  await page.route("**/stub-api/content", (route) =>
    route.fulfill({ json: [] }),
  );
}

test("a sandbox says whose it is, when it expires, and what to do first", async ({
  page,
}) => {
  await signInAsAdmin(page, "sandbox");
  await page.goto("/content");

  await expect(page.getByText("Acme Co", { exact: true })).toBeVisible();
  await expect(page.getByText("Demo workspace")).toHaveCount(0);
  await expect(page.getByText(/This is a sandbox workspace/)).toBeVisible();
  await expect(page).toHaveTitle("Content · Acme Co");

  const checklist = page.getByRole("region", { name: "Set up Acme Co" });
  await expect(
    checklist.getByRole("link", { name: "Invite a teammate" }),
  ).toBeVisible();
  await expect(
    checklist.getByRole("button", { name: "Load sample guidelines" }),
  ).toBeVisible();

  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});

test("the demo workspace is badged, with no expiry and no checklist", async ({
  page,
}) => {
  await signInAsAdmin(page, "demo");
  await page.goto("/content");

  await expect(page.getByText("Demo workspace")).toBeVisible();
  await expect(page.getByText(/This is a sandbox workspace/)).toHaveCount(0);
  await expect(page.getByRole("region", { name: /Set up/ })).toHaveCount(0);
});

test("an admin adds a person, and the last admin can't be removed", async ({
  page,
}) => {
  await signInAsAdmin(page, "sandbox");
  const people = [{ ...ADMIN }];
  await page.route("**/stub-api/admin/users", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      people.push({ id: "user-new", tag: null, ...body });
      return route.fulfill({ status: 201, json: people.at(-1) });
    }
    return route.fulfill({ json: people });
  });
  await page.route("**/stub-api/admin/users/user-admin", (route) =>
    route.fulfill({
      status: 409,
      json: { detail: "A workspace needs at least one admin." },
    }),
  );

  await page.goto("/people");
  await page.getByLabel("Name", { exact: true }).fill("Sam");
  await page.getByLabel("Email").fill("sam@acme.example");
  await page.getByLabel("First password (8+ characters)").fill("long-enough-pw");
  await page.getByRole("button", { name: "Add person" }).click();
  await expect(page.getByText("sam@acme.example")).toBeVisible();

  await page.getByLabel("Role for Ada").selectOption("creator");
  await expect(
    page.locator("main").getByRole("alert").filter({ hasText: "at least one admin" }),
  ).toBeVisible();
});
