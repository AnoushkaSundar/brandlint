import { readFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { type Finding } from "../lib/contracts";
import { type Chunk } from "../lib/engineClient";
import {
  type Highlight,
  highlightsByChunk,
  segmentText,
  sortFindings,
} from "../lib/highlights";

const WCAG_22_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const DEMO = join(__dirname, "..", "..", "demo");
const ENGINE_ID = "rev-demo-agency-blog";

function demoJson<T>(...parts: string[]): T {
  return JSON.parse(readFileSync(join(DEMO, ...parts), "utf-8"));
}

const FINDINGS = demoJson<Finding[]>("findings", "agency-blog.json");
const CHUNKS: Chunk[] = demoJson<{ chunk_id: string; text: string }[]>(
  "pieces",
  "agency-blog.chunks.json",
).map((chunk, ordinal) => ({
  ...chunk,
  ordinal,
  kind: chunk.chunk_id.endsWith("-h1") ? "heading" : "paragraph",
}));

const CONTENT = {
  id: "c1",
  title: "First week guide",
  channel: "blog",
  source: "Stellfield Creative",
  data_class: "public",
  state: "ai_review",
  creator_id: "user-creator",
  created_at: "2026-11-05T10:00:00Z",
  versions: [
    {
      id: "v1",
      content_id: "c1",
      version: 1,
      text: "",
      file_name: null,
      created_by: "user-creator",
      created_at: "2026-11-05T10:00:00Z",
    },
  ],
  latest_review: {
    id: "r1",
    content_version_id: "v1",
    engine_review_id: ENGINE_ID,
    channel: "blog",
    rulebook_version: 1,
    created_at: "2026-11-05T10:00:00Z",
  },
};

function stream(findings: readonly Finding[], finished = true): string {
  const events = findings.map(
    (finding) => `event: finding\ndata: ${JSON.stringify(finding)}\n\n`,
  );
  if (finished) {
    events.push(`event: done\ndata: {"count": ${findings.length}}\n\n`);
  }
  return events.join("");
}

async function stubReview(
  page: Page,
  { content = CONTENT as unknown, chunks = CHUNKS, findings = FINDINGS } = {},
) {
  await page.route("**/stub-api/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "user-creator",
        email: "creator@tarnhollow.example",
        name: "Test creator",
        role: "creator",
        tag: null,
      },
    }),
  );
  await page.route("**/stub-api/content/c1", (route) =>
    route.fulfill({ json: content }),
  );
  await page.route(`**/stub-api/engine/reviews/${ENGINE_ID}/chunks`, (route) =>
    route.fulfill({ json: chunks }),
  );
  await page.route(`**/stub-api/engine/reviews/${ENGINE_ID}/findings`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: stream(findings),
    }),
  );
}

function findingCards(page: Page) {
  return page
    .getByRole("region", { name: "Findings" })
    .getByRole("button");
}

function highlight(page: Page, text: string) {
  return page.locator("mark").filter({ hasText: text });
}

function cardFor(page: Page, explanation: string) {
  return findingCards(page).filter({ hasText: explanation });
}

async function expectNoAccessibilityViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(WCAG_22_AA)
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test.describe("segmenting text", () => {
  const mark = (
    start: number,
    end: number,
    severity: Highlight["severity"] = "low",
    findingId = "a",
  ): Highlight => ({ findingId, severity, start, end });

  test("text with no highlights stays whole", () => {
    expect(segmentText("Hello", [])).toEqual([
      { text: "Hello", start: 0, findingIds: [], severity: null },
    ]);
  });

  test("a highlight splits the text around it", () => {
    expect(segmentText("Hello there", [mark(6, 11)]).map((s) => s.text)).toEqual([
      "Hello ",
      "there",
    ]);
  });

  test("the pieces always rejoin into the original", () => {
    const text = "Starting a new job is strange";
    const parts = segmentText(text, [mark(0, 8), mark(4, 12), mark(20, 29)]);

    expect(parts.map((s) => s.text).join("")).toBe(text);
  });

  test("overlapping highlights show the worst severity and both findings", () => {
    const parts = segmentText("abcdefgh", [
      mark(0, 5, "low", "first"),
      mark(3, 8, "critical", "second"),
    ]);

    expect(parts.map((s) => [s.text, s.severity, s.findingIds])).toEqual([
      ["abc", "low", ["first"]],
      ["de", "critical", ["first", "second"]],
      ["fgh", "critical", ["second"]],
    ]);
  });

  test("a span past the end of the text is cut short", () => {
    const parts = segmentText("Hello", [mark(3, 99)]);

    expect(parts.map((s) => s.text)).toEqual(["Hel", "lo"]);
  });

  test("empty spans aren't highlighted", () => {
    const finding = {
      ...FINDINGS[0],
      spans: [{ chunk_id: "blog-p1", start: 4, end: 4 }],
    };

    expect(highlightsByChunk([finding]).size).toBe(0);
  });
});

test.describe("sorting findings", () => {
  const order = new Map(CHUNKS.map((chunk) => [chunk.chunk_id, chunk.ordinal]));

  test("runs from critical to low", () => {
    const severities = sortFindings(FINDINGS, order).map((f) => f.severity);

    expect(severities).toEqual([
      "critical",
      "high",
      "high",
      "high",
      "medium",
      "medium",
      "low",
    ]);
  });

  test("uses position within the same severity", () => {
    const high = sortFindings(FINDINGS, order).filter(
      (f) => f.severity === "high",
    );

    expect(high.map((f) => f.spans[0].chunk_id)).toEqual([
      "blog-p2",
      "blog-p3",
      "blog-p4",
    ]);
  });

  test("findings with no span go last in their severity", () => {
    const noSpan = { ...FINDINGS[0], id: "x", severity: "low" as const, spans: [] };
    const low = FINDINGS.find((f) => f.severity === "low") as Finding;

    expect(sortFindings([noSpan, low], order).map((f) => f.id)).toEqual([
      low.id,
      "x",
    ]);
  });
});

test.describe("review screen", () => {
  test("shows the document with its planted issues highlighted", async ({
    page,
  }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    await expect(page).toHaveTitle("Review · BrandLint");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "First week guide",
    );
    await expect(page.locator("main")).toContainText(
      "Version 1 reviewed against rulebook version 1",
    );
    await expect(
      page.getByRole("heading", { name: "Your first week shapes" }),
    ).toBeVisible();

    for (const text of [
      "best-in-class",
      "Tarnhollow Onramp",
      "newbies",
      "Bluewren",
      "by 80%",
      "cut onboarding time",
    ]) {
      await expect(highlight(page, text)).toBeVisible();
    }
  });

  test("lists every finding, most serious first", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    await expect(findingCards(page)).toHaveCount(FINDINGS.length);
    await expect(findingCards(page).first()).toContainText("Critical");
    await expect(findingCards(page).last()).toContainText("Low");
  });

  test("reports when the review has finished", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    await expect(
      page.locator("main").getByRole("status"),
    ).toHaveText("Finished: 7 findings");
  });

  test("marks an UNSURE finding for a reviewer", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    await expect(
      findingCards(page).filter({ hasText: "Needs a reviewer" }),
    ).toHaveCount(1);
  });

  test("selecting a claim marks both of its parts", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    await cardFor(page, "claim an 80% cut").click();

    await expect(highlight(page, "cut onboarding time")).toHaveAttribute(
      "data-selected",
      "true",
    );
    await expect(highlight(page, "by 80%")).toHaveAttribute(
      "data-selected",
      "true",
    );
    await expect(highlight(page, "newbies")).not.toHaveAttribute(
      "data-selected",
      "true",
    );
  });

  test("clicking a highlight selects its finding", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    await highlight(page, "Bluewren").getByRole("button").click();

    await expect(cardFor(page, "unreleased product")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  test("highlights work from the keyboard", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    const button = highlight(page, "newbies").getByRole("button");
    await button.focus();
    await page.keyboard.press("Enter");

    await expect(cardFor(page, "new hire rather than newbie")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  test("severity reaches screen readers as well as colour", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    await expect(
      page.getByRole("button", { name: "Bluewren (critical finding)" }),
    ).toBeVisible();
  });

  test("a dropped stream says so", async ({ page }) => {
    await stubReview(page);
    await page.route(
      `**/stub-api/engine/reviews/${ENGINE_ID}/findings`,
      (route) => route.abort(),
    );
    await page.goto("/content/c1/review");

    await expect(page.locator("main").getByRole("alert")).toContainText(
      "stopped before it finished",
    );
  });

  test("a repeated finding is only shown once", async ({ page }) => {
    await stubReview(page, { findings: [FINDINGS[0], FINDINGS[0]] });
    await page.goto("/content/c1/review");

    await expect(page.locator("main").getByRole("status")).toHaveText(
      "Finished: 1 finding",
    );
    await expect(findingCards(page)).toHaveCount(1);
  });

  test("clean content says nothing was found", async ({ page }) => {
    await stubReview(page, { findings: [] });
    await page.goto("/content/c1/review");

    await expect(page.locator("main")).toContainText("No issues found.");
  });

  test("content without a review says so", async ({ page }) => {
    await stubReview(page, { content: { ...CONTENT, latest_review: null } });
    await page.goto("/content/c1/review");

    await expect(page.locator("main")).toContainText("hasn't been reviewed yet");
  });

  test("an uploaded image is shown with alt text", async ({ page }) => {
    const version = { ...CONTENT.versions[0], file_name: "banner.png" };
    await stubReview(page, {
      content: { ...CONTENT, versions: [version] },
      chunks: [{ chunk_id: "banner-image", ordinal: 0, kind: "image", text: "" }],
      findings: [],
    });
    await page.goto("/content/c1/review");

    const image = page.getByRole("img", { name: /uploaded image/ });
    await expect(image).toHaveAttribute(
      "src",
      /\/content\/versions\/v1\/file$/,
    );
  });
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the panes stack and nothing scrolls sideways", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");
    await expect(findingCards(page)).toHaveCount(FINDINGS.length);

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
});

test.describe("accessibility (WCAG 2.2 AA)", () => {
  test("the review screen has no violations", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");
    await expect(findingCards(page)).toHaveCount(FINDINGS.length);
    await expectNoAccessibilityViolations(page);
  });

  test("a selected finding has no violations", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");
    await cardFor(page, "claim an 80% cut").click();
    await expect(cardFor(page, "claim an 80% cut")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expectNoAccessibilityViolations(page);
  });
});
