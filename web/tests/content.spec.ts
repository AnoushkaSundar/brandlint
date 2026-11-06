import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const ALL_ROLES = ["creator", "reviewer", "manager", "legal", "admin"];
const WCAG_22_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

function userFor(role: string) {
  return {
    id: `user-${role}`,
    email: `${role}@tarnhollow.example`,
    name: `Test ${role}`,
    role,
    tag: null,
  };
}

const SUMMARY = {
  id: "c1",
  title: "First week guide",
  channel: "linkedin",
  source: "in-house",
  data_class: "public",
  state: "draft",
  creator_id: "user-creator",
  created_at: "2026-11-05T10:00:00Z",
};

function version(number: number, text: string, file_name: string | null = null) {
  return {
    id: `v${number}`,
    content_id: "c1",
    version: number,
    text,
    file_name,
    created_by: "user-creator",
    created_at: "2026-11-05T10:00:00Z",
  };
}

const DETAIL = {
  ...SUMMARY,
  versions: [version(2, "Second draft"), version(1, "First draft")],
  latest_review: null,
};

const REVIEW = {
  id: "r1",
  content_version_id: "v2",
  engine_review_id: "rev-demo-linkedin-post",
  channel: "linkedin",
  rulebook_version: 1,
  created_at: "2026-11-05T10:00:00Z",
};

async function signInAs(page: Page, role: string) {
  await page.route("**/stub-api/auth/me", (route) =>
    route.fulfill({ json: userFor(role) }),
  );
}

async function stubList(page: Page, items: unknown[]) {
  await page.route("**/stub-api/content", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: items })
      : route.fallback(),
  );
}

async function stubDetail(page: Page, detail: unknown) {
  await page.route("**/stub-api/content/c1", (route) =>
    route.fulfill({ json: detail }),
  );
}

async function expectNoAccessibilityViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(WCAG_22_AA)
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

function formError(page: Page) {
  return page.locator("main").getByRole("alert");
}

test.describe("content list", () => {
  test("shows submitted content", async ({ page }) => {
    await signInAs(page, "reviewer");
    await stubList(page, [SUMMARY]);
    await page.goto("/content");

    const row = page.getByRole("row", { name: /First week guide/ });
    await expect(row).toContainText("LinkedIn");
    await expect(row).toContainText("in-house");
    await expect(row).toContainText("Draft");
    await row.getByRole("link").click();
    await expect(page).toHaveURL("/content/c1");
  });

  test("only creators are offered New content", async ({ page }) => {
    await signInAs(page, "creator");
    await stubList(page, []);
    await page.goto("/content");

    await expect(page.getByRole("link", { name: "New content" })).toBeVisible();
    await expect(page.locator("main")).toContainText("Submit your first draft");
  });

  for (const role of ALL_ROLES.filter((r) => r !== "creator")) {
    test(`${role} isn't offered New content`, async ({ page }) => {
      await signInAs(page, role);
      await stubList(page, []);
      await page.goto("/content");

      await expect(page.locator("main")).toContainText("Nothing has been submitted");
      await expect(page.getByRole("link", { name: "New content" })).toHaveCount(0);
    });
  }

  test("shows an error when the list can't load", async ({ page }) => {
    await signInAs(page, "creator");
    await page.route("**/stub-api/content", (route) =>
      route.fulfill({ status: 500, json: { detail: "Database is down" } }),
    );
    await page.goto("/content");

    await expect(formError(page)).toHaveText("Database is down");
  });
});

test.describe("new content", () => {
  test("pasting text saves a draft and opens it", async ({ page }) => {
    await signInAs(page, "creator");
    await stubDetail(page, DETAIL);
    await page.route("**/stub-api/content", (route) =>
      route.fulfill({ status: 201, json: DETAIL }),
    );
    await page.goto("/content/new");

    await page.getByLabel("Title").fill("First week guide");
    await page.getByLabel("Channel").click();
    await page.getByRole("option", { name: "LinkedIn" }).click();
    await page.getByLabel("Data class").click();
    await page.getByRole("option", { name: "Public" }).click();
    await page.getByLabel("Source").fill("Stellfield Creative");
    await page.getByLabel("Paste your text").fill("Hello there");

    const request = page.waitForRequest("**/stub-api/content");
    await page.getByRole("button", { name: "Save draft" }).click();

    const sent = (await request).postData() ?? "";
    const headers = (await request).headers();
    expect(headers["content-type"]).toContain("multipart/form-data");
    for (const value of [
      "First week guide",
      "linkedin",
      "public",
      "Stellfield Creative",
      "Hello there",
    ]) {
      expect(sent).toContain(value);
    }
    await expect(page).toHaveURL("/content/c1");
  });

  test("a file is sent with its name", async ({ page }) => {
    await signInAs(page, "creator");
    await stubDetail(page, DETAIL);
    await page.route("**/stub-api/content", (route) =>
      route.fulfill({ status: 201, json: DETAIL }),
    );
    await page.goto("/content/new");

    await page.getByLabel("Title").fill("Banner");
    await page.getByLabel("Or upload a file").setInputFiles({
      name: "banner.png",
      mimeType: "image/png",
      buffer: Buffer.from("fake image"),
    });

    const request = page.waitForRequest("**/stub-api/content");
    await page.getByRole("button", { name: "Save draft" }).click();

    expect((await request).postData() ?? "").toContain('filename="banner.png"');
  });

  test("a refused upload shows why and keeps the form", async ({ page }) => {
    await signInAs(page, "creator");
    await page.route("**/stub-api/content", (route) =>
      route.fulfill({
        status: 422,
        json: { detail: "That file isn't a valid PDF." },
      }),
    );
    await page.goto("/content/new");

    await page.getByLabel("Title").fill("Guide");
    await page.getByRole("button", { name: "Save draft" }).click();

    await expect(formError(page)).toHaveText("That file isn't a valid PDF.");
    await expect(page.getByLabel("Title")).toHaveValue("Guide");
    await expect(page.getByRole("button", { name: "Save draft" })).toBeEnabled();
  });

  test("a validation list from the API shows a plain message", async ({ page }) => {
    await signInAs(page, "creator");
    await page.route("**/stub-api/content", (route) =>
      route.fulfill({ status: 422, json: { detail: [{ loc: ["title"] }] } }),
    );
    await page.goto("/content/new");

    await page.getByLabel("Title").fill("Guide");
    await page.getByRole("button", { name: "Save draft" }).click();

    await expect(formError(page)).toContainText("Something went wrong");
  });

  test("other roles are told they can't submit", async ({ page }) => {
    await signInAs(page, "reviewer");
    await page.goto("/content/new");

    await expect(page.locator("main")).toContainText("Only creators");
    await expect(page.getByLabel("Title")).toHaveCount(0);
  });
});

test.describe("content detail", () => {
  test("shows the details and every version, newest first", async ({ page }) => {
    await signInAs(page, "creator");
    await stubDetail(page, DETAIL);
    await page.goto("/content/c1");

    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "First week guide",
    );
    await expect(page.locator("main")).toContainText("LinkedIn");
    await expect(page.locator("main")).toContainText("Second draft");
    await expect(page.locator("main").getByRole("listitem")).toContainText([
      "Version 2",
      "Version 1",
    ]);
  });

  test("saving an edit adds a version", async ({ page }) => {
    await signInAs(page, "creator");
    let detail = DETAIL;
    await page.route("**/stub-api/content/c1", (route) =>
      route.fulfill({ json: detail }),
    );
    await page.route("**/stub-api/content/c1/versions", (route) => {
      detail = {
        ...DETAIL,
        versions: [version(3, "Third draft"), ...DETAIL.versions],
      };
      return route.fulfill({ status: 201, json: detail });
    });
    await page.goto("/content/c1");

    await page.getByLabel("Edit the text").fill("Third draft");
    const request = page.waitForRequest("**/stub-api/content/c1/versions");
    await page.getByRole("button", { name: "Save as new version" }).click();

    expect((await request).postData() ?? "").toContain("Third draft");
    await expect(page.locator("main").getByRole("listitem").first()).toContainText(
      "Version 3",
    );
    await expect(page.getByLabel("Edit the text")).toHaveValue("Third draft");
  });

  test("starting a review opens the review screen", async ({ page }) => {
    await signInAs(page, "creator");
    await stubDetail(page, DETAIL);
    await page.route("**/stub-api/content/c1/reviews", (route) =>
      route.fulfill({ status: 201, json: REVIEW }),
    );
    await page.goto("/content/c1");

    const request = page.waitForRequest("**/stub-api/content/c1/reviews");
    await page.getByRole("button", { name: "Start review" }).click();

    expect((await request).method()).toBe("POST");
    await expect(page).toHaveURL("/content/c1/review");
  });

  test("a current review is opened, not restarted", async ({ page }) => {
    await signInAs(page, "creator");
    await stubDetail(page, { ...DETAIL, latest_review: REVIEW });
    await page.goto("/content/c1");

    await expect(page.getByRole("link", { name: "Open review" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Start review" })).toHaveCount(0);
  });

  test("a new version can be reviewed again", async ({ page }) => {
    await signInAs(page, "creator");
    await stubDetail(page, {
      ...DETAIL,
      latest_review: { ...REVIEW, content_version_id: "v1" },
    });
    await page.goto("/content/c1");

    await expect(page.getByRole("button", { name: "Start review" })).toBeVisible();
  });

  test("a reviewer can read but not change anything", async ({ page }) => {
    await signInAs(page, "reviewer");
    await stubDetail(page, DETAIL);
    await page.goto("/content/c1");

    await expect(page.locator("main")).toContainText("Second draft");
    await expect(page.getByLabel("Edit the text")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Start review" })).toHaveCount(0);
  });

  test("published content can't be edited", async ({ page }) => {
    await signInAs(page, "creator");
    await stubDetail(page, { ...DETAIL, state: "published" });
    await page.goto("/content/c1");

    await expect(page.locator("main")).toContainText("Published");
    await expect(page.getByLabel("Edit the text")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Start review" })).toHaveCount(0);
  });

  test("uploaded files are linked", async ({ page }) => {
    await signInAs(page, "creator");
    await stubDetail(page, {
      ...DETAIL,
      versions: [version(1, "", "banner.png")],
    });
    await page.goto("/content/c1");

    await expect(page.getByRole("link", { name: "banner.png" })).toHaveAttribute(
      "href",
      /\/content\/versions\/v1\/file$/,
    );
  });

  test("missing content shows a message", async ({ page }) => {
    await signInAs(page, "creator");
    await page.route("**/stub-api/content/c1", (route) =>
      route.fulfill({ status: 404, json: { detail: "Content not found" } }),
    );
    await page.goto("/content/c1");

    await expect(formError(page)).toHaveText("Content not found");
  });
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the list scrolls inside its own box", async ({ page }) => {
    await signInAs(page, "creator");
    await stubList(page, [SUMMARY]);
    await page.goto("/content");
    await expect(page.getByRole("table")).toBeVisible();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
});

test.describe("accessibility (WCAG 2.2 AA)", () => {
  test("the list has no violations", async ({ page }) => {
    await signInAs(page, "creator");
    await stubList(page, [SUMMARY]);
    await page.goto("/content");
    await expect(page.getByRole("table")).toBeVisible();
    await expectNoAccessibilityViolations(page);
  });

  test("the form has no violations", async ({ page }) => {
    await signInAs(page, "creator");
    await page.goto("/content/new");
    await expect(page.getByLabel("Title")).toBeVisible();
    await expectNoAccessibilityViolations(page);
  });

  test("the form error has no violations", async ({ page }) => {
    await signInAs(page, "creator");
    await page.route("**/stub-api/content", (route) =>
      route.fulfill({ status: 422, json: { detail: "Paste some text." } }),
    );
    await page.goto("/content/new");
    await page.getByLabel("Title").fill("Guide");
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(formError(page)).toBeVisible();
    await expectNoAccessibilityViolations(page);
  });

  test("the detail page has no violations", async ({ page }) => {
    await signInAs(page, "creator");
    await stubDetail(page, DETAIL);
    await page.goto("/content/c1");
    await expect(page.getByLabel("Edit the text")).toBeVisible();
    await expectNoAccessibilityViolations(page);
  });
});
