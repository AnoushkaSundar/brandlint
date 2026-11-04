import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

// Written out by hand rather than imported from lib/navigation.ts, so a mistake
// in the navigation config fails this test instead of agreeing with it.
const NAV_BY_ROLE = {
  Creator: ["Content"],
  Reviewer: ["Content", "Review queue"],
  Manager: ["Content", "Approvals", "Insights", "Audit log"],
  Legal: ["Content", "Approvals"],
  Admin: [
    "Content",
    "Rulebook",
    "Facts",
    "Terms",
    "Assets",
    "Insights",
    "Proposals",
    "Memory graph",
    "Audit log",
  ],
};

const ROUTES = [
  { path: "/content", title: "Content" },
  { path: "/queue", title: "Review queue" },
  { path: "/approvals", title: "Approvals" },
  { path: "/brand/rulebook", title: "Rulebook" },
  { path: "/brand/facts", title: "Facts" },
  { path: "/brand/terms", title: "Terms" },
  { path: "/brand/assets", title: "Assets" },
  { path: "/insights", title: "Insights" },
  { path: "/proposals", title: "Proposals" },
  { path: "/graph", title: "Memory graph" },
  { path: "/audit", title: "Audit log" },
];

const WCAG_22_AA = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
];

function mainNav(page: Page) {
  return page.getByRole("navigation", { name: "Main" });
}

async function previewRole(page: Page, role: string) {
  await page.getByRole("combobox", { name: "Preview role" }).click();
  await page.getByRole("option", { name: role, exact: true }).click();
}

async function expectNoAccessibilityViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(WCAG_22_AA)
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test("the home page sends people to Content", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL("/content");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Content");
});

test.describe("navigation by role", () => {
  for (const [role, expected] of Object.entries(NAV_BY_ROLE)) {
    test(`${role} sees only their links`, async ({ page }) => {
      await page.goto("/content");
      await previewRole(page, role);
      await expect(mainNav(page).getByRole("link")).toHaveText(expected);
    });
  }

  test("a new session starts on the least-privileged role", async ({
    page,
  }) => {
    await page.goto("/content");
    await expect(mainNav(page).getByRole("link")).toHaveText(
      NAV_BY_ROLE.Creator,
    );
  });

  test("switching to a role that lacks the page returns to Content", async ({
    page,
  }) => {
    await page.goto("/content");
    await previewRole(page, "Admin");
    await mainNav(page).getByRole("link", { name: "Facts" }).click();
    await expect(page).toHaveURL("/brand/facts");

    await previewRole(page, "Creator");
    await expect(page).toHaveURL("/content");
  });

  test("switching to a role that has the page stays on it", async ({
    page,
  }) => {
    await page.goto("/content");
    await previewRole(page, "Admin");
    await mainNav(page).getByRole("link", { name: "Audit log" }).click();
    await expect(page).toHaveURL("/audit");

    await previewRole(page, "Manager");
    await expect(page).toHaveURL("/audit");
  });
});

test.describe("routes", () => {
  for (const { path, title } of ROUTES) {
    test(`${path} loads with a heading and page title`, async ({ page }) => {
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
      await expect(page).toHaveTitle(`${title} · BrandLint`);
    });
  }

  test("the current page is marked in the navigation", async ({ page }) => {
    await page.goto("/content");
    await previewRole(page, "Admin");
    await mainNav(page).getByRole("link", { name: "Insights" }).click();
    await expect(page).toHaveURL("/insights");

    await expect(
      mainNav(page).getByRole("link", { name: "Insights" }),
    ).toHaveAttribute("aria-current", "page");
    await expect(
      mainNav(page).getByRole("link", { name: "Content" }),
    ).not.toHaveAttribute("aria-current");
  });
});

test.describe("keyboard", () => {
  test("the skip link is the first tab stop and moves focus to main", async ({
    page,
  }) => {
    await page.goto("/content");
    await page.keyboard.press("Tab");

    const skipLink = page.getByRole("link", { name: "Skip to main content" });
    await expect(skipLink).toBeFocused();
    await expect(skipLink).toBeInViewport();

    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
  });

  test("the role preview works from the keyboard", async ({ page }) => {
    await page.goto("/content");
    await page.getByRole("combobox", { name: "Preview role" }).focus();
    await page.keyboard.press("Enter");
    await page.getByRole("option", { name: "Legal", exact: true }).focus();
    await page.keyboard.press("Enter");

    await expect(mainNav(page).getByRole("link")).toHaveText(
      NAV_BY_ROLE.Legal,
    );
  });
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the menu opens, navigates and closes", async ({ page }) => {
    await page.goto("/content");
    await expect(mainNav(page)).toBeHidden();

    await previewRole(page, "Admin");
    await page.getByRole("button", { name: "Toggle Sidebar" }).click();
    await mainNav(page).getByRole("link", { name: "Facts" }).click();

    await expect(page).toHaveURL("/brand/facts");
    await expect(page.getByRole("dialog")).toBeHidden();
  });

  test("nothing scrolls sideways", async ({ page }) => {
    await page.goto("/content");
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
});

test.describe("accessibility (WCAG 2.2 AA)", () => {
  for (const { path } of ROUTES) {
    test(`${path} has no violations`, async ({ page }) => {
      await page.goto(path);
      await expectNoAccessibilityViolations(page);
    });
  }

  test("the admin navigation has no violations", async ({ page }) => {
    await page.goto("/content");
    await previewRole(page, "Admin");
    await expect(mainNav(page).getByRole("link")).toHaveCount(
      NAV_BY_ROLE.Admin.length,
    );
    await expectNoAccessibilityViolations(page);
  });

  test("the open role menu has no violations", async ({ page }) => {
    await page.goto("/content");
    await page.getByRole("combobox", { name: "Preview role" }).click();
    await expect(page.getByRole("listbox")).toBeVisible();
    await expectNoAccessibilityViolations(page);
  });

  test.describe("on mobile", () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test("the open menu has no violations", async ({ page }) => {
      await page.goto("/content");
      await page.getByRole("button", { name: "Toggle Sidebar" }).click();
      await expect(mainNav(page)).toBeVisible();
      await expectNoAccessibilityViolations(page);
    });
  });
});
