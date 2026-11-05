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

type RoleName = keyof typeof NAV_BY_ROLE;

const ROUTES: { path: string; title: string; role: RoleName }[] = [
  { path: "/content", title: "Content", role: "Creator" },
  { path: "/queue", title: "Review queue", role: "Reviewer" },
  { path: "/approvals", title: "Approvals", role: "Legal" },
  { path: "/brand/rulebook", title: "Rulebook", role: "Admin" },
  { path: "/brand/facts", title: "Facts", role: "Admin" },
  { path: "/brand/terms", title: "Terms", role: "Admin" },
  { path: "/brand/assets", title: "Assets", role: "Admin" },
  { path: "/insights", title: "Insights", role: "Manager" },
  { path: "/proposals", title: "Proposals", role: "Admin" },
  { path: "/graph", title: "Memory graph", role: "Admin" },
  { path: "/audit", title: "Audit log", role: "Manager" },
];

const WCAG_22_AA = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
];

function userFor(role: RoleName) {
  return {
    id: `user-${role}`,
    email: `${role.toLowerCase()}@tarnhollow.example`,
    name: `Test ${role}`,
    role: role.toLowerCase(),
    tag: null,
  };
}

const NOT_SIGNED_IN = { status: 401, json: { detail: "Not signed in" } };

async function signInAs(page: Page, role: RoleName) {
  await page.route("**/stub-api/auth/me", (route) =>
    route.fulfill({ json: userFor(role) }),
  );
}

async function signedOut(page: Page) {
  await page.route("**/stub-api/auth/me", (route) =>
    route.fulfill(NOT_SIGNED_IN),
  );
}

async function fillLoginForm(page: Page) {
  await page.getByLabel("Email").fill("admin@tarnhollow.example");
  await page.getByLabel("Password").fill("a-password");
  await page.getByRole("button", { name: "Sign in" }).click();
}

// Scoped to the form because Next.js adds its own role="alert" route announcer.
function loginError(page: Page) {
  return page.locator("form").getByRole("alert");
}

function mainNav(page: Page) {
  return page.getByRole("navigation", { name: "Main" });
}

async function expectNoAccessibilityViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(WCAG_22_AA)
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test("the home page sends people to Content", async ({ page }) => {
  await signInAs(page, "Creator");
  await page.goto("/");
  await expect(page).toHaveURL("/content");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Content");
});

test.describe("signing in", () => {
  test("someone signed out is sent to sign in", async ({ page }) => {
    await signedOut(page);
    await page.goto("/brand/facts");

    await expect(page).toHaveURL("/login?next=%2Fbrand%2Ffacts");
    await expect(page).toHaveTitle("Sign in · BrandLint");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Sign in to BrandLint",
    );
  });

  test("signing in returns to the page that was asked for", async ({
    page,
  }) => {
    let signedIn = false;
    await page.route("**/stub-api/auth/me", (route) =>
      signedIn
        ? route.fulfill({ json: userFor("Admin") })
        : route.fulfill(NOT_SIGNED_IN),
    );
    await page.route("**/stub-api/auth/login", (route) => {
      signedIn = true;
      return route.fulfill({
        json: {
          access_token: "token",
          token_type: "bearer",
          user: userFor("Admin"),
        },
      });
    });

    await page.goto("/brand/facts");
    await expect(page).toHaveURL(/\/login/);
    await fillLoginForm(page);

    await expect(page).toHaveURL("/brand/facts");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Facts");
  });

  test("the form sends the email and password as JSON", async ({ page }) => {
    await signedOut(page);
    await page.route("**/stub-api/auth/login", (route) =>
      route.fulfill({ json: { user: userFor("Admin") } }),
    );
    await page.goto("/login");

    const request = page.waitForRequest("**/stub-api/auth/login");
    await fillLoginForm(page);

    expect((await request).postDataJSON()).toEqual({
      email: "admin@tarnhollow.example",
      password: "a-password",
    });
  });

  test("a wrong password shows the error and stays on the page", async ({
    page,
  }) => {
    await page.route("**/stub-api/auth/login", (route) =>
      route.fulfill({
        status: 401,
        json: { detail: "Email or password is incorrect" },
      }),
    );
    await page.goto("/login");
    await fillLoginForm(page);

    await expect(loginError(page)).toHaveText(
      "Email or password is incorrect",
    );
    await expect(page).toHaveURL("/login");
    await expect(page.getByLabel("Email")).toHaveValue(
      "admin@tarnhollow.example",
    );
    await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  test("an unreachable server shows a clear message", async ({ page }) => {
    await page.route("**/stub-api/auth/login", (route) => route.abort());
    await page.goto("/login");
    await fillLoginForm(page);

    await expect(loginError(page)).toContainText(
      "couldn't reach the server",
    );
  });

  for (const next of ["//evil.example", "https://evil.example", "/\\evil.example"]) {
    test(`a crafted link to ${next} can't redirect off the site`, async ({
      page,
    }) => {
      await page.route("**/stub-api/auth/login", (route) =>
        route.fulfill({ json: { user: userFor("Admin") } }),
      );
      await signInAs(page, "Admin");
      await page.goto(`/login?next=${encodeURIComponent(next)}`);
      await fillLoginForm(page);

      await expect(page).toHaveURL("/content");
    });
  }

  test("the fields help password managers", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel("Email")).toHaveAttribute(
      "autocomplete",
      "username",
    );
    const password = page.getByLabel("Password");
    await expect(password).toHaveAttribute("type", "password");
    await expect(password).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
  });

  test("the form works from the keyboard", async ({ page }) => {
    await page.route("**/stub-api/auth/login", (route) =>
      route.fulfill({ json: { user: userFor("Admin") } }),
    );
    await signInAs(page, "Admin");
    await page.goto("/login");

    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Email")).toBeFocused();
    await page.keyboard.type("admin@tarnhollow.example");
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Password")).toBeFocused();
    await page.keyboard.type("a-password");
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL("/content");
  });
});

test.describe("the signed-in user", () => {
  test("appears in the header", async ({ page }) => {
    await signInAs(page, "Reviewer");
    await page.goto("/content");

    const banner = page.getByRole("banner");
    await expect(banner).toContainText("Test Reviewer");
    await expect(banner).toContainText("Reviewer");
  });

  test("can sign out", async ({ page }) => {
    await signInAs(page, "Admin");
    await page.route("**/stub-api/auth/logout", (route) =>
      route.fulfill({ status: 204 }),
    );
    await page.goto("/content");

    const request = page.waitForRequest("**/stub-api/auth/logout");
    await page.getByRole("button", { name: "Sign out" }).click();

    expect((await request).method()).toBe("POST");
    await expect(page).toHaveURL("/login");
  });

  test("is sent to sign in when the session ends", async ({ page }) => {
    let sessionActive = true;
    await page.route("**/stub-api/auth/me", (route) =>
      sessionActive
        ? route.fulfill({ json: userFor("Admin") })
        : route.fulfill(NOT_SIGNED_IN),
    );
    await page.goto("/content");
    await expect(mainNav(page)).toBeVisible();

    sessionActive = false;
    await mainNav(page).getByRole("link", { name: "Facts" }).click();

    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("navigation by role", () => {
  for (const [role, expected] of Object.entries(NAV_BY_ROLE)) {
    test(`${role} sees only their links`, async ({ page }) => {
      await signInAs(page, role as RoleName);
      await page.goto("/content");
      await expect(mainNav(page).getByRole("link")).toHaveText(expected);
    });
  }

  test("a role can't open another role's page by URL", async ({ page }) => {
    await signInAs(page, "Creator");
    await page.goto("/brand/facts");

    await expect(page).toHaveURL("/content");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Content");
  });
});

test.describe("routes", () => {
  for (const { path, title, role } of ROUTES) {
    test(`${path} loads for ${role}`, async ({ page }) => {
      await signInAs(page, role);
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
      await expect(page).toHaveTitle(`${title} · BrandLint`);
    });
  }

  test("the current page is marked in the navigation", async ({ page }) => {
    await signInAs(page, "Admin");
    await page.goto("/content");
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
    await signInAs(page, "Creator");
    await page.goto("/content");
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible();
    await page.keyboard.press("Tab");

    const skipLink = page.getByRole("link", { name: "Skip to main content" });
    await expect(skipLink).toBeFocused();
    await expect(skipLink).toBeInViewport();

    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
  });
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the menu opens, navigates and closes", async ({ page }) => {
    await signInAs(page, "Admin");
    await page.goto("/content");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(mainNav(page)).toBeHidden();

    await page.getByRole("button", { name: "Toggle Sidebar" }).click();
    await mainNav(page).getByRole("link", { name: "Facts" }).click();

    await expect(page).toHaveURL("/brand/facts");
    await expect(page.getByRole("dialog")).toBeHidden();
  });

  test("nothing scrolls sideways", async ({ page }) => {
    await signInAs(page, "Admin");
    await page.goto("/content");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });

  test("the sign-in page fits", async ({ page }) => {
    await page.goto("/login");
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
});

test.describe("accessibility (WCAG 2.2 AA)", () => {
  for (const { path, title, role } of ROUTES) {
    test(`${path} has no violations`, async ({ page }) => {
      await signInAs(page, role);
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
      await expectNoAccessibilityViolations(page);
    });
  }

  test("the admin navigation has no violations", async ({ page }) => {
    await signInAs(page, "Admin");
    await page.goto("/content");
    await expect(mainNav(page).getByRole("link")).toHaveCount(
      NAV_BY_ROLE.Admin.length,
    );
    await expectNoAccessibilityViolations(page);
  });

  test("the sign-in page has no violations", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel("Email")).toBeVisible();
    await expectNoAccessibilityViolations(page);
  });

  test("the sign-in error has no violations", async ({ page }) => {
    await page.route("**/stub-api/auth/login", (route) =>
      route.fulfill({
        status: 401,
        json: { detail: "Email or password is incorrect" },
      }),
    );
    await page.goto("/login");
    await fillLoginForm(page);
    await expect(loginError(page)).toBeVisible();
    await expectNoAccessibilityViolations(page);
  });

  test.describe("on mobile", () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test("the open menu has no violations", async ({ page }) => {
      await signInAs(page, "Admin");
      await page.goto("/content");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.getByRole("button", { name: "Toggle Sidebar" }).click();
      await expect(mainNav(page)).toBeVisible();
      await expectNoAccessibilityViolations(page);
    });
  });
});
