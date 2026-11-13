import { readFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  type Chunk,
  type DecisionAction,
  type Finding,
} from "../lib/contracts";
import { trackProgress } from "../lib/findingLabels";
import {
  type Highlight,
  highlightsByChunk,
  segmentText,
  sortFindings,
} from "../lib/highlights";
import { wordDiff } from "../lib/wordDiff";
import { type Board } from "../lib/workflow";

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
).map(({ chunk_id, text }, ordinal) => ({
  id: chunk_id,
  content_version_id: "cv-demo-agency-blog-1",
  ordinal,
  kind: chunk_id.endsWith("-h1") ? "heading" : "paragraph",
  text,
  content_hash: "hash",
  data_class: "public",
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

const RULES = demoJson<{ id: string; clause_ref: string }[]>(
  "brand",
  "rules.json",
);

function creatorActions(finding: Finding): DecisionAction[] {
  if (finding.verdict !== "VIOLATION") return [];
  const fixes: DecisionAction[] = finding.fix_available
    ? ["accept_fix", "edit_fix"]
    : [];
  return ["low", "medium"].includes(finding.severity)
    ? [...fixes, "override"]
    : fixes;
}

function boardFor(findings: readonly Finding[] = FINDINGS): Board {
  return {
    state: "resolving",
    legal_required: false,
    can_restart: false,
    hidden_overridden: false,
    findings: findings.map((finding) => ({
      id: finding.id,
      status: "open",
      fix_text: null,
      allowed: creatorActions(finding),
    })),
    moves: [],
  };
}

const STATUS_AFTER = {
  accept_fix: "fix_accepted",
  edit_fix: "fix_edited",
  override: "override_pending",
  confirm_override: "override_confirmed",
  reject_override: "override_rejected",
  resolve: "resolved",
} as const;

type Posted = {
  findingId: string;
  action: DecisionAction;
  reason?: string;
  fix_text?: string;
};

/** Serves the board and applies decisions to it, recording what was sent. */
async function stubBoard(page: Page, start: Board = boardFor()) {
  let board = start;
  const decisions: Posted[] = [];
  const moves: { to: string; reason?: string }[] = [];

  await page.route("**/stub-api/workflow/content/c1/board", (route) =>
    route.fulfill({ json: board }),
  );
  await page.route(
    "**/stub-api/workflow/content/c1/findings/*/decisions",
    (route) => {
      const findingId = decodeURIComponent(
        route.request().url().split("/findings/")[1].split("/")[0],
      );
      const body = route.request().postDataJSON();
      decisions.push({ findingId, ...body });
      const action = body.action as DecisionAction;
      board = {
        ...board,
        findings: board.findings.map((item) =>
          item.id === findingId
            ? { ...item, status: STATUS_AFTER[action], allowed: [] }
            : item,
        ),
      };
      return route.fulfill({ status: 201, json: board });
    },
  );
  await page.route("**/stub-api/workflow/content/c1/transitions", (route) => {
    const body = route.request().postDataJSON();
    moves.push(body);
    board = { ...board, state: body.to, moves: [] };
    return route.fulfill({ json: board });
  });
  return { decisions, moves };
}

async function stubReview(
  page: Page,
  { content = CONTENT as unknown, chunks = CHUNKS, findings = FINDINGS } = {},
) {
  await stubBoard(page, boardFor(findings));
  await page.route("**/stub-api/admin/rulebook*", (route) =>
    route.fulfill({ json: RULES }),
  );
  await page.route("**/stub-api/workflow/content/c1/comments", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/stub-api/memory/precedents*", (route) =>
    route.fulfill({ json: [] }),
  );
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
    .getByRole("article");
}

function card(page: Page, explanation: string) {
  return findingCards(page).filter({ hasText: explanation });
}

function highlight(page: Page, text: string) {
  return page.locator("mark").filter({ hasText: text });
}

function cardFor(page: Page, explanation: string) {
  return findingCards(page).getByRole("button", { name: explanation });
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
  const order = new Map(CHUNKS.map((chunk) => [chunk.id, chunk.ordinal]));

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
  test("a highlight keeps the spaces around it", async ({ page }) => {
    // Real reviews often mark " best-in-class " with its edge spaces. Inside a button those
    // spaces are dropped by the browser, which made "the best-in-class way" read
    // "thebest-in-classway".
    const text = "It is the best-in-class way to help people settle in.";
    const start = text.indexOf(" best-in-class ");
    const chunk = { ...CHUNKS[0], id: "spaced", kind: "paragraph" as const, text };
    const finding = {
      ...FINDINGS[0],
      spans: [{ chunk_id: "spaced", start, end: start + " best-in-class ".length }],
    };
    await stubReview(page, { chunks: [chunk], findings: [finding] });
    await page.goto("/content/c1/review");

    const paragraph = page.locator("p").filter({ has: highlight(page, "best-in-class") });
    await expect(paragraph).toBeVisible();
    // The highlight carries a screen-reader label, which can add a line break to innerText.
    // Only whitespace is normalised, so words glued together still fail.
    const painted = (await paragraph.innerText())
      .replace(/\s+/g, " ")
      .replace(/ ?\((critical|high|medium|low) finding\)/, "")
      .replace(/\s+/g, " ")
      .trim();
    expect(painted).toBe(text);
  });

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
      chunks: [
        {
          id: "banner-image",
          content_version_id: "v1",
          ordinal: 0,
          kind: "image",
          text: "",
          content_hash: "hash",
          data_class: "public",
        },
      ],
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

const BASE = FINDINGS[0];
const REPLAY = {
  identical: true,
  verdict: "VIOLATION",
  manifest: {
    rule_id: "R-TERM-02",
    rule_version: 1,
    fact_ids: [],
    models: ["claude-haiku-4-5"],
    as_of: "2026-11-07",
  },
};

function fixFor(attempt: 1 | 2, suggested = "Tarnhollow Landing") {
  return {
    finding_id: BASE.id,
    original: "Tarnhollow Onramp",
    suggested,
    diff: "- Tarnhollow Onramp\n+ Tarnhollow Landing",
    attempt,
  };
}

/** Answers each fix request in turn, repeating the last answer. */
async function stubFixes(
  page: Page,
  answers: { status?: number; json: unknown }[],
) {
  let call = 0;
  const asked: boolean[] = [];
  await page.route(
    "**/stub-api/workflow/content/c1/findings/*/fix",
    (route) => {
      asked.push(route.request().postDataJSON().again);
      const answer = answers[Math.min(call, answers.length - 1)];
      call += 1;
      return route.fulfill(answer);
    },
  );
  return asked;
}

test.describe("comparing words", () => {
  test("identical text has one unchanged part", () => {
    expect(wordDiff("a new hire", "a new hire")).toEqual([
      { kind: "same", text: "a new hire" },
    ]);
  });

  test("a changed word leaves the rest alone", () => {
    expect(wordDiff("Tarnhollow Onramp", "Tarnhollow Landing")).toEqual([
      { kind: "same", text: "Tarnhollow " },
      { kind: "removed", text: "Onramp" },
      { kind: "added", text: "Landing" },
    ]);
  });

  test("the parts rebuild both versions", () => {
    const before = "cut onboarding time for every new starter by 80%";
    const after = "cut onboarding time for new hires by 38% on average";
    const parts = wordDiff(before, after);

    const rebuild = (skip: string) =>
      parts
        .filter((part) => part.kind !== skip)
        .map((part) => part.text)
        .join("");
    expect(rebuild("added")).toBe(before);
    expect(rebuild("removed")).toBe(after);
  });
});

test.describe("reading progress from findings", () => {
  const coded = { ...BASE, tier: 0 as const };
  const ai = { ...BASE, tier: 1 as const, unit_type: "chunk" as const };
  const claim = { ...BASE, tier: 1 as const, unit_type: "claim" as const };
  const whole = { ...BASE, tier: 1 as const, unit_type: "document" as const };

  test("sorts findings into their tracks", () => {
    expect(
      trackProgress([coded, coded, ai, claim, whole], true).map(
        (track) => track.count,
      ),
    ).toEqual([2, 1, 1, 1]);
  });

  test("code checks finish when the first AI finding arrives", () => {
    const [code, chunk] = trackProgress([coded, ai], false);

    expect(code.done).toBe(true);
    expect(chunk.done).toBe(false);
  });

  test("nothing is done before the stream says so", () => {
    expect(
      trackProgress([coded], false).some((track) => track.done),
    ).toBe(false);
  });

  test("everything is done when the stream ends", () => {
    expect(trackProgress([], true).every((track) => track.done)).toBe(true);
  });
});

test.describe("finding cards", () => {
  test("show severity, check, confidence and the explanation", async ({
    page,
  }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    const found = card(page, "claim an 80% cut");
    await expect(found).toContainText("High");
    await expect(found).toContainText("Claim");
    await expect(found).toContainText("97% confidence");
  });

  test("quote the source with its rule, clause and version", async ({
    page,
  }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    const found = card(page, "retired name");
    await expect(found.locator("blockquote")).toContainText(
      "The product is Tarnhollow Landing.",
    );
    await expect(found.locator("figcaption")).toHaveText(
      "Rule it breaks · R-TERM-02 §3.2, version 1",
    );
  });

  test("still quote the source if the rulebook can't load", async ({
    page,
  }) => {
    await stubReview(page);
    await page.route("**/stub-api/admin/rulebook*", (route) => route.abort());
    await page.goto("/content/c1/review");

    const found = card(page, "retired name");
    await expect(found.locator("blockquote")).toBeVisible();
    await expect(found.locator("figcaption")).toHaveText(
      "Rule it breaks · R-TERM-02, version 1",
    );
  });

  test("badge AI findings with the model and code findings as code", async ({
    page,
  }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    const aiFinding = FINDINGS.find((item) => item.ai_generated);
    await expect(card(page, "claim an 80% cut")).toContainText(
      `AI: ${aiFinding?.models_used[0]}`,
    );
    await expect(card(page, "retired name")).toContainText("Code check");
  });

  test("explain themselves only when asked", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    const found = card(page, "retired name");
    const step = found.getByText("Matched the renamed term");
    await expect(step).toBeHidden();

    await found.getByText("Why was this flagged?").click();

    await expect(step).toBeVisible();
    await expect(found).toContainText("Sources: R-TERM-02 §3.2");
  });

  test("report a split vote", async ({ page }) => {
    await stubReview(page, {
      findings: [
        {
          ...BASE,
          vote: { variants: 3, agree: 2, split: true },
        },
      ],
    });
    await page.goto("/content/c1/review");
    await findingCards(page).getByText("Why was this flagged?").click();

    await expect(findingCards(page)).toContainText(
      "2 of 3 rubrics agreed, so the vote was split.",
    );
  });

  test("label a precedent as context only", async ({ page }) => {
    await stubReview(page);
    await page.route("**/stub-api/memory/precedents*", (route) =>
      route.fulfill({
        json: [
          {
            decision_id: "d1",
            rule_id: "R-TERM-03",
            rule_version: 1,
            channel: "blog",
            reason: "Used in a direct quote from a customer.",
            reviewer: "Lena Fischer",
            date: "2026-10-12",
          },
        ],
      }),
    );
    await page.goto("/content/c1/review");

    const found = card(page, "retired name");
    await expect(found).toContainText("Earlier decision, context only");
    await expect(found).toContainText("Lena Fischer, 12 Oct 2026");
  });

  test("leave precedents out when there are none or the lookup fails", async ({
    page,
  }) => {
    await stubReview(page);
    await page.route("**/stub-api/memory/precedents*", (route) =>
      route.abort(),
    );
    await page.goto("/content/c1/review");

    await expect(findingCards(page)).toHaveCount(FINDINGS.length);
    await expect(page.locator("main")).not.toContainText("context only");
    await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
  });

  test("an UNSURE finding with no confidence shows no score and no fix", async ({
    page,
  }) => {
    await stubReview(page, {
      findings: [
        {
          ...BASE,
          verdict: "UNSURE",
          confidence: 0,
          fix_available: false,
          explanation: "The model couldn't decide.",
        },
      ],
    });
    await page.goto("/content/c1/review");

    const found = card(page, "couldn't decide");
    await expect(found).toContainText("Needs a reviewer");
    await expect(found).not.toContainText("confidence");
    await expect(found.getByRole("button", { name: "Suggest fix" })).toHaveCount(
      0,
    );
  });

  test("several UNSURE findings on one chunk are all listed", async ({
    page,
  }) => {
    await stubReview(page, {
      findings: ["a", "b", "c"].map((letter) => ({
        ...BASE,
        id: `unsure-${letter}`,
        verdict: "UNSURE" as const,
        confidence: 0,
        fix_available: false,
        explanation: `Unsure about ${letter}.`,
      })),
    });
    await page.goto("/content/c1/review");

    await expect(
      findingCards(page).filter({ hasText: "Needs a reviewer" }),
    ).toHaveCount(3);
  });

  test("a security rule is named, with no clause or version", async ({
    page,
  }) => {
    await stubReview(page, {
      findings: [
        {
          ...BASE,
          check: "hidden_content",
          rule_id: "SEC-HIDDEN-CONTENT",
          rule_version: null,
          cited_text: "Content must not hide text from the reader.",
          explanation: "This text is hidden from the reader.",
        },
      ],
    });
    await page.goto("/content/c1/review");

    const found = card(page, "hidden from the reader");
    await expect(found.locator("blockquote")).toContainText("must not hide");
    await expect(found.locator("figcaption")).toHaveText(
      "Rule it breaks · BrandLint security rule",
    );
  });

  test("a codename finding cites its rule without any fact", async ({
    page,
  }) => {
    await stubReview(page, {
      findings: [
        {
          ...BASE,
          rule_id: "R-CLAIM-05",
          rule_version: 1,
          fact_ids: [],
          cited_text: "Never name an unreleased product.",
          explanation: "This names an unreleased product.",
        },
      ],
    });
    await page.goto("/content/c1/review");

    await expect(
      card(page, "unreleased product").locator("figcaption"),
    ).toContainText("R-CLAIM-05");
  });

  test("a document-level finding says so and highlights nothing", async ({
    page,
  }) => {
    await stubReview(page, {
      findings: [
        {
          ...BASE,
          check: "required_element",
          unit_type: "document",
          spans: [],
          rule_id: "R-REQ-01",
          explanation: "The disclaimer is missing.",
        },
      ],
    });
    await page.goto("/content/c1/review");

    const found = card(page, "disclaimer is missing");
    await expect(found).toContainText("Applies to the whole document.");
    await expect(page.locator("mark")).toHaveCount(0);

    await cardFor(page, "disclaimer is missing").click();

    await expect(cardFor(page, "disclaimer is missing")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  test("a zero-length span counts as the whole document", async ({ page }) => {
    await stubReview(page, {
      findings: [
        {
          ...BASE,
          unit_type: "document",
          spans: [{ chunk_id: "blog-p1", start: 0, end: 0 }],
          explanation: "The disclaimer is missing.",
        },
      ],
    });
    await page.goto("/content/c1/review");

    await expect(card(page, "disclaimer is missing")).toContainText(
      "Applies to the whole document.",
    );
  });

  test("tracks say stopped after a dropped stream", async ({ page }) => {
    await stubReview(page);
    await page.route(
      `**/stub-api/engine/reviews/${ENGINE_ID}/findings`,
      (route) => route.abort(),
    );
    await page.goto("/content/c1/review");

    const progress = page.getByRole("list", { name: "Progress" });
    await expect(progress).toContainText("Code checks: 0, stopped");
    await expect(progress).not.toContainText("checking");
  });

  test("a contrast finding previews the pair and a colour that passes", async ({
    page,
  }) => {
    await stubReview(page);
    await stubBoard(page);
    await stubReview(page, {
      findings: [
        {
          ...BASE,
          check: "accessibility",
          rule_id: "WCAG-1.4.3",
          rule_version: null,
          explanation: "This text has low contrast.",
          trace: {
            ...BASE.trace,
            steps: [
              {
                tool: "contrast_preview",
                input_summary: "#AAAAAA on #FFFFFF",
                output_summary: "2.3:1, needs 4.5:1, try #12343B",
              },
            ],
          },
        },
      ],
    });
    await page.goto("/content/c1/review");

    const found = card(page, "low contrast");
    await expect(found).toContainText("Text #AAAAAA");
    await expect(found).toContainText("Background #FFFFFF");
    await expect(found).toContainText("2.3:1, needs 4.5:1");
    await expect(found).toContainText("Try #12343B");
  });

  test("progress is shown for every track", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    const progress = page.getByRole("list", { name: "Progress" });
    await expect(progress.getByRole("listitem")).toHaveCount(4);
    await expect(progress).toContainText("Code checks: 5, done");
    await expect(progress).toContainText("Claims: 1, done");
  });
});

test.describe("suggesting a fix", () => {
  const suggestFix = (page: Page) =>
    card(page, "retired name").getByRole("button", { name: "Suggest fix" });

  test("is only offered when a fix is available", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    await expect(suggestFix(page)).toBeVisible();
    await expect(
      card(page, "Bluewren").getByRole("button", { name: "Suggest fix" }),
    ).toHaveCount(0);
  });

  test("shows the change as tracked changes", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();

    const found = card(page, "retired name");
    await expect(found).toContainText("attempt 1 of 2");
    await expect(found.locator("del")).toContainText("Onramp");
    await expect(found.locator("ins")).toContainText("Landing");
  });

  test("nothing changes until someone clicks", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    await expect(card(page, "retired name").locator("ins")).toBeVisible();

    await expect(highlight(page, "Tarnhollow Onramp")).toBeVisible();
    await expect(card(page, "retired name")).not.toContainText("Fix accepted");
  });

  test("accepting saves it and ends the offer", async ({ page }) => {
    await stubReview(page);
    const { decisions } = await stubBoard(page);
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    await card(page, "retired name")
      .getByRole("button", { name: "Accept" })
      .click();

    await expect(card(page, "retired name")).toContainText("Fix accepted");
    await expect(suggestFix(page)).toHaveCount(0);
    expect(decisions).toEqual([
      { findingId: BASE.id, action: "accept_fix", attempt: 1 },
    ]);
  });

  test("editing starts from the suggestion and needs some text", async ({
    page,
  }) => {
    await stubReview(page);
    const { decisions } = await stubBoard(page);
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    const found = card(page, "retired name");
    await found.getByRole("button", { name: "Edit" }).click();

    const field = found.getByLabel("Your version");
    await expect(field).toHaveValue("Tarnhollow Landing");

    await field.fill("   ");
    await expect(found.getByRole("button", { name: "Save edit" })).toBeDisabled();

    await field.fill("The Tarnhollow Landing app");
    await found.getByRole("button", { name: "Save edit" }).click();

    await expect(found).toContainText("Fix waiting for a reviewer");
    expect(decisions[0]).toMatchObject({
      action: "edit_fix",
      fix_text: "The Tarnhollow Landing app",
    });
  });

  test("going back from editing keeps the suggestion", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    const found = card(page, "retired name");
    await found.getByRole("button", { name: "Edit" }).click();
    await found.getByRole("button", { name: "Back to suggestion" }).click();

    await expect(found.locator("ins")).toContainText("Landing");
  });

  test("closing leaves the finding open", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    await card(page, "retired name")
      .getByRole("button", { name: "Close" })
      .click();

    await expect(suggestFix(page)).toBeVisible();
  });

  test("a second attempt is offered once", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [
      { json: fixFor(1) },
      { json: fixFor(2, "Tarnhollow Landing today") },
    ]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    const found = card(page, "retired name");
    await found.getByRole("button", { name: "Try another" }).click();

    await expect(found).toContainText("attempt 2 of 2");
    await expect(found.getByRole("button", { name: "Try another" })).toHaveCount(
      0,
    );
  });

  test("two failed attempts end in the agreed message", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [
      { status: 422, json: { detail: "No safe fix found; marked for review" } },
    ]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();

    const found = card(page, "retired name");
    await expect(found.getByRole("alert")).toHaveText(
      "No safe fix found; marked for review",
    );
    await expect(found.getByRole("button", { name: "Try again" })).toHaveCount(
      0,
    );
  });

  test("is labelled as an AI suggestion", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();

    await expect(card(page, "retired name")).toContainText("AI suggestion");
  });

  test("reopening doesn't spend an attempt", async ({ page }) => {
    await stubReview(page);
    const asked = await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    await card(page, "retired name")
      .getByRole("button", { name: "Close" })
      .click();
    await suggestFix(page).click();

    await expect(card(page, "retired name")).toContainText("attempt 1 of 2");
    expect(asked).toEqual([false, false]);
  });

  test("trying another spends an attempt", async ({ page }) => {
    await stubReview(page);
    const asked = await stubFixes(page, [
      { json: fixFor(1) },
      { json: fixFor(2) },
    ]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    await card(page, "retired name")
      .getByRole("button", { name: "Try another" })
      .click();

    await expect(card(page, "retired name")).toContainText("attempt 2 of 2");
    expect(asked).toEqual([false, true]);
  });

  test("a failed second attempt keeps the first fix", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [
      { json: fixFor(1) },
      { status: 422, json: { detail: "No safe fix" } },
    ]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    const found = card(page, "retired name");
    await found.getByRole("button", { name: "Try another" }).click();

    await expect(found.getByRole("alert")).toHaveText(
      "No safe fix found; marked for review",
    );
    await expect(found.locator("ins")).toContainText("Landing");
    await expect(found.getByRole("button", { name: "Accept" })).toBeVisible();
    await expect(found.getByRole("button", { name: "Try another" })).toHaveCount(
      0,
    );
  });

  test("a failed fix can be closed", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [
      { status: 422, json: { detail: "No safe fix" } },
    ]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    await card(page, "retired name")
      .getByRole("button", { name: "Close" })
      .click();

    await expect(suggestFix(page)).toBeVisible();
  });

  test("a server problem can be tried again", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [
      { status: 500, json: {} },
      { json: fixFor(1) },
    ]);
    await page.goto("/content/c1/review");

    await suggestFix(page).click();
    const found = card(page, "retired name");
    await found.getByRole("button", { name: "Try again" }).click();

    await expect(found.locator("ins")).toContainText("Landing");
  });
});

test.describe("replaying a verdict", () => {
  const replay = (page: Page) =>
    card(page, "retired name").getByRole("button", { name: "Replay" });

  test("confirms an identical result and lists its inputs", async ({ page }) => {
    await stubReview(page);
    await page.route("**/stub-api/engine/verdicts/*/replay", (route) =>
      route.fulfill({ json: REPLAY }),
    );
    await page.goto("/content/c1/review");

    await replay(page).click();

    const found = card(page, "retired name");
    await expect(found.getByRole("status")).toHaveText("Identical result ✓");
    await expect(found.locator("dl")).toContainText("Rule version");
    await expect(found).toContainText("claude-haiku-4-5");
  });

  test("shows the real engine's inputs in readable form", async ({ page }) => {
    await stubReview(page);
    await page.route("**/stub-api/engine/verdicts/*/replay", (route) =>
      route.fulfill({
        json: {
          identical: true,
          verdict: "VIOLATION",
          manifest: {
            kind: "language",
            chunk_id: "blog-p2",
            content_hash: "abc123",
            rule: { id: "R-TONE-01", version: 1, text: "Be warm." },
            facts: [{ id: "F-001", version: 1 }],
            model: "claude-haiku-4-5",
            flagged: false,
            as_of: "2026-11-07",
          },
        },
      }),
    );
    await page.goto("/content/c1/review");

    await replay(page).click();

    const inputs = card(page, "retired name").locator("dl");
    await expect(inputs).toContainText("R-TONE-01, version 1");
    await expect(inputs).toContainText("F-001, version 1");
    await expect(inputs).not.toContainText("[object Object]");
    await expect(inputs).not.toContainText("abc123");
  });

  test("works when the engine sends no inputs", async ({ page }) => {
    await stubReview(page);
    await page.route("**/stub-api/engine/verdicts/*/replay", (route) =>
      route.fulfill({ json: { identical: true, verdict: "VIOLATION" } }),
    );
    await page.goto("/content/c1/review");

    await replay(page).click();

    await expect(card(page, "retired name").getByRole("status")).toHaveText(
      "Identical result ✓",
    );
  });

  test("says so when the result differs", async ({ page }) => {
    await stubReview(page);
    await page.route("**/stub-api/engine/verdicts/*/replay", (route) =>
      route.fulfill({ json: { ...REPLAY, identical: false, verdict: "UNSURE" } }),
    );
    await page.goto("/content/c1/review");

    await replay(page).click();

    await expect(card(page, "retired name").getByRole("status")).toHaveText(
      "Different result: UNSURE",
    );
  });

  test("a failed re-run doesn't leave the old result behind", async ({
    page,
  }) => {
    await stubReview(page);
    let calls = 0;
    await page.route("**/stub-api/engine/verdicts/*/replay", (route) => {
      calls += 1;
      return calls === 1
        ? route.fulfill({ json: REPLAY })
        : route.fulfill({ status: 500, json: { detail: "That failed." } });
    });
    await page.goto("/content/c1/review");

    await replay(page).click();
    const found = card(page, "retired name");
    await expect(found.getByRole("status")).toHaveText("Identical result ✓");

    await replay(page).click();

    await expect(found.getByRole("alert")).toHaveText("That failed.");
    await expect(found).not.toContainText("Identical result");
  });

  test("reports a failure", async ({ page }) => {
    await stubReview(page);
    await page.route("**/stub-api/engine/verdicts/*/replay", (route) =>
      route.fulfill({ status: 404, json: { detail: "Finding not found" } }),
    );
    await page.goto("/content/c1/review");

    await replay(page).click();

    await expect(card(page, "retired name").getByRole("alert")).toHaveText(
      "Finding not found",
    );
  });
});

test.describe("deciding on a finding", () => {
  const low = () => FINDINGS.find((item) => item.severity === "low") as Finding;
  const unsure = () =>
    FINDINGS.find((item) => item.verdict === "UNSURE") as Finding;

  function reviewerBoard(status: "open" | "override_pending"): Board {
    const board = boardFor();
    return {
      ...board,
      findings: board.findings.map((item) => {
        if (item.id === low().id && status === "override_pending") {
          return {
            ...item,
            status,
            allowed: ["confirm_override", "reject_override"],
          };
        }
        if (item.id === unsure().id) return { ...item, allowed: ["resolve"] };
        return { ...item, allowed: [] };
      }),
    };
  }

  test("a creator can only override what the server allows", async ({
    page,
  }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    await expect(
      card(page, low().explanation).getByRole("button", { name: "Override" }),
    ).toBeVisible();
    await expect(
      card(page, "retired name").getByRole("button", { name: "Override" }),
    ).toHaveCount(0);
    await expect(
      card(page, "Bluewren").getByRole("button", { name: "Override" }),
    ).toHaveCount(0);
  });

  test("no fix is offered unless the server allows it", async ({ page }) => {
    await stubReview(page);
    await stubBoard(page, {
      ...boardFor(),
      findings: boardFor().findings.map((item) => ({ ...item, allowed: [] })),
    });
    await page.goto("/content/c1/review");
    await expect(page.getByRole("region", { name: "Workflow" })).toBeVisible();

    await expect(page.getByRole("button", { name: "Suggest fix" })).toHaveCount(
      0,
    );
  });

  test("an override needs a reason and then waits for a reviewer", async ({
    page,
  }) => {
    await stubReview(page);
    const { decisions } = await stubBoard(page);
    await page.goto("/content/c1/review");

    const found = card(page, low().explanation);
    await found.getByRole("button", { name: "Override" }).click();

    const submit = found.getByRole("button", { name: "Submit override" });
    await expect(submit).toBeDisabled();

    await found.getByLabel("Why should this be overridden?").fill("A quote");
    await submit.click();

    await expect(found).toContainText("Override waiting for a reviewer");
    expect(decisions).toEqual([
      { findingId: low().id, action: "override", reason: "A quote" },
    ]);
  });

  test("cancelling an override sends nothing", async ({ page }) => {
    await stubReview(page);
    const { decisions } = await stubBoard(page);
    await page.goto("/content/c1/review");

    const found = card(page, low().explanation);
    await found.getByRole("button", { name: "Override" }).click();
    await found.getByRole("button", { name: "Cancel" }).click();

    await expect(found.getByRole("button", { name: "Override" })).toBeVisible();
    expect(decisions).toEqual([]);
  });

  test("a refused decision shows why and keeps the reason", async ({ page }) => {
    await stubReview(page);
    await page.route(
      "**/stub-api/workflow/content/c1/findings/*/decisions",
      (route) =>
        route.fulfill({
          status: 403,
          json: { detail: "You can't do that to this finding." },
        }),
    );
    await page.goto("/content/c1/review");

    const found = card(page, low().explanation);
    await found.getByRole("button", { name: "Override" }).click();
    const field = found.getByLabel("Why should this be overridden?");
    await field.fill("A quote");
    await found.getByRole("button", { name: "Submit override" }).click();

    await expect(found.getByRole("alert")).toHaveText(
      "You can't do that to this finding.",
    );
    await expect(field).toHaveValue("A quote");
  });

  test("a reason form closes once the decision is saved", async ({ page }) => {
    await stubReview(page);
    await page.goto("/content/c1/review");

    const found = card(page, low().explanation);
    await found.getByRole("button", { name: "Override" }).click();
    await found.getByLabel("Why should this be overridden?").fill("A quote");
    await found.getByRole("button", { name: "Submit override" }).click();

    await expect(found).toContainText("Override waiting for a reviewer");
    await expect(found.getByLabel("Why should this be overridden?")).toHaveCount(
      0,
    );
  });

  test("a failed save keeps the edit", async ({ page }) => {
    await stubReview(page);
    await page.route(
      "**/stub-api/workflow/content/c1/findings/*/decisions",
      (route) =>
        route.fulfill({ status: 409, json: { detail: "Not any more." } }),
    );
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");

    const found = card(page, "retired name");
    await found.getByRole("button", { name: "Suggest fix" }).click();
    await found.getByRole("button", { name: "Edit" }).click();
    await found.getByLabel("Your version").fill("My careful wording");
    await found.getByRole("button", { name: "Save edit" }).click();

    await expect(found.getByRole("alert")).toHaveText("Not any more.");
    await expect(found.getByLabel("Your version")).toHaveValue(
      "My careful wording",
    );
  });

  test("a refused fix shows why", async ({ page }) => {
    await stubReview(page);
    await page.route(
      "**/stub-api/workflow/content/c1/findings/*/decisions",
      (route) =>
        route.fulfill({ status: 403, json: { detail: "Not any more." } }),
    );
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");

    const found = card(page, "retired name");
    await found.getByRole("button", { name: "Suggest fix" }).click();
    await found.getByRole("button", { name: "Accept" }).click();

    await expect(found.getByRole("alert")).toHaveText("Not any more.");
  });

  test("a reviewer confirms a pending override", async ({ page }) => {
    await stubReview(page);
    const { decisions } = await stubBoard(page, reviewerBoard("override_pending"));
    await page.goto("/content/c1/review");

    const found = card(page, low().explanation);
    await expect(found).toContainText("Override waiting for a reviewer");
    await found.getByRole("button", { name: "Confirm override" }).click();

    await expect(found).toContainText("Override confirmed");
    expect(decisions[0]).toMatchObject({ action: "confirm_override" });
  });

  test("a reviewer rejects an override with a reason", async ({ page }) => {
    await stubReview(page);
    const { decisions } = await stubBoard(page, reviewerBoard("override_pending"));
    await page.goto("/content/c1/review");

    const found = card(page, low().explanation);
    await found.getByRole("button", { name: "Reject override" }).click();
    await found.getByLabel("Why is this override rejected?").fill("Not a quote");
    await found.getByRole("button", { name: "Reject", exact: true }).click();

    await expect(found).toContainText("Override rejected");
    expect(decisions[0]).toMatchObject({
      action: "reject_override",
      reason: "Not a quote",
    });
  });

  test("a reviewer resolves an UNSURE finding with a reason", async ({
    page,
  }) => {
    await stubReview(page);
    const { decisions } = await stubBoard(page, reviewerBoard("open"));
    await page.goto("/content/c1/review");

    const found = card(page, unsure().explanation);
    await found.getByRole("button", { name: "Resolve" }).click();
    await found.getByLabel("How was this settled?").fill("Fine in context");
    await found.getByRole("button", { name: "Mark resolved" }).click();

    await expect(found).toContainText("Resolved");
    expect(decisions[0]).toMatchObject({
      action: "resolve",
      reason: "Fine in context",
    });
  });

  test("a reviewer signs off an edited fix and sees its wording", async ({
    page,
  }) => {
    await stubReview(page);
    const board = boardFor();
    const { decisions } = await stubBoard(page, {
      ...board,
      findings: board.findings.map((item) =>
        item.id === BASE.id
          ? {
              ...item,
              status: "fix_edited",
              fix_text: "The Landing app",
              allowed: ["resolve", "reject_override"],
            }
          : { ...item, allowed: [] },
      ),
    });
    await page.goto("/content/c1/review");

    const found = card(page, "retired name");
    await expect(found).toContainText("Fix waiting for a reviewer");
    await expect(found).toContainText("Wording: The Landing app");
    await expect(found.getByRole("button", { name: "Reject fix" })).toBeVisible();

    await found.getByRole("button", { name: "Sign off" }).click();
    await found.getByLabel("Why is this fix fine?").fill("Reads well");
    await found.getByRole("button", { name: "Sign off" }).click();

    await expect(found).toContainText("Resolved");
    expect(decisions[0]).toMatchObject({ action: "resolve", reason: "Reads well" });
  });

  test("a settled finding loses its highlight", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.goto("/content/c1/review");
    await expect(highlight(page, "Tarnhollow Onramp")).toBeVisible();

    const found = card(page, "retired name");
    await found.getByRole("button", { name: "Suggest fix" }).click();
    await found.getByRole("button", { name: "Accept" }).click();

    await expect(found).toContainText("Fix accepted");
    await expect(highlight(page, "Tarnhollow Onramp")).toHaveCount(0);
  });
});

test.describe("moving content through the workflow", () => {
  const bar = (page: Page) => page.getByRole("region", { name: "Workflow" });

  test("shows the status and why a move is blocked", async ({ page }) => {
    await stubReview(page);
    await stubBoard(page, {
      ...boardFor(),
      moves: [
        {
          to: "reviewer_check",
          needs_reason: false,
          blocked_by: "7 findings still open",
        },
      ],
    });
    await page.goto("/content/c1/review");

    await expect(bar(page)).toContainText("Status: Resolving");
    await expect(
      bar(page).getByRole("button", { name: "Submit for review" }),
    ).toBeDisabled();
    await expect(bar(page)).toContainText("7 findings still open");
  });

  test("makes a move and shows the new status", async ({ page }) => {
    await stubReview(page);
    const { moves } = await stubBoard(page, {
      ...boardFor(),
      moves: [{ to: "reviewer_check", needs_reason: false, blocked_by: null }],
    });
    await page.goto("/content/c1/review");

    await bar(page).getByRole("button", { name: "Submit for review" }).click();

    await expect(bar(page)).toContainText("Status: Reviewer check");
    expect(moves).toHaveLength(1);
    expect(moves[0].to).toBe("reviewer_check");
  });

  test("asks for a reason where one is needed", async ({ page }) => {
    await stubReview(page);
    const { moves } = await stubBoard(page, {
      ...boardFor(),
      moves: [{ to: "rejected", needs_reason: true, blocked_by: null }],
    });
    await page.goto("/content/c1/review");

    await bar(page).getByRole("button", { name: "Reject" }).click();
    expect(moves).toEqual([]);

    await bar(page).getByLabel("Why: reject?").fill("Off brand");
    await bar(page).getByRole("button", { name: "Reject" }).click();

    await expect(bar(page)).toContainText("Status: Rejected");
    expect(moves[0]).toMatchObject({ to: "rejected", reason: "Off brand" });
  });

  test("a refused move shows why", async ({ page }) => {
    await stubReview(page);
    await stubBoard(page, {
      ...boardFor(),
      moves: [{ to: "published", needs_reason: false, blocked_by: null }],
    });
    await page.route("**/stub-api/workflow/content/c1/transitions", (route) =>
      route.fulfill({
        status: 409,
        json: { detail: "A high-severity claim needs legal sign-off first" },
      }),
    );
    await page.goto("/content/c1/review");

    await bar(page).getByRole("button", { name: "Publish" }).click();

    await expect(bar(page).getByRole("alert")).toContainText("legal sign-off");
  });

  test("says when legal must sign off", async ({ page }) => {
    await stubReview(page);
    await stubBoard(page, { ...boardFor(), legal_required: true });
    await page.goto("/content/c1/review");

    await expect(bar(page)).toContainText("legal must sign this off");
  });

  test("leaves AI review by itself when the stream ends", async ({ page }) => {
    await stubReview(page);
    const { moves } = await stubBoard(page, {
      ...boardFor(),
      state: "ai_review",
      moves: [{ to: "resolving", needs_reason: false, blocked_by: null }],
    });
    await page.goto("/content/c1/review");

    await expect(bar(page)).toContainText("Status: Resolving");
    expect(moves).toHaveLength(1);
    expect(moves[0].to).toBe("resolving");
  });

  test("stays in AI review while the run isn't finished", async ({ page }) => {
    await stubReview(page);
    const { moves } = await stubBoard(page, {
      ...boardFor(),
      state: "ai_review",
      moves: [
        {
          to: "resolving",
          needs_reason: false,
          blocked_by: "The review is still running",
        },
      ],
    });
    await page.goto("/content/c1/review");

    await expect(bar(page)).toContainText("Status: AI review");
    await expect(bar(page)).toContainText("The review is still running");
    expect(moves).toEqual([]);
  });

  test("moves on by itself once a dropped stream's run ends", async ({
    page,
  }) => {
    await stubReview(page);
    const blocked = {
      ...boardFor(),
      state: "ai_review" as const,
      moves: [
        {
          to: "resolving" as const,
          needs_reason: false,
          blocked_by: "The review is still running",
        },
      ],
    };
    await stubBoard(page, blocked);
    await page.route(
      `**/stub-api/engine/reviews/${ENGINE_ID}/findings`,
      (route) => route.abort(),
    );
    let reads = 0;
    await page.route("**/stub-api/workflow/content/c1/board", (route) => {
      reads += 1;
      return route.fulfill({
        json:
          reads === 1
            ? blocked
            : {
                ...blocked,
                moves: [{ ...blocked.moves[0], blocked_by: null }],
              },
      });
    });
    await page.goto("/content/c1/review");

    await expect(bar(page)).toContainText("Status: Resolving");
  });

  test("a failed run can be started again", async ({ page }) => {
    await stubReview(page);
    const failed = {
      ...boardFor(),
      state: "ai_review" as const,
      can_restart: true,
      moves: [
        {
          to: "resolving" as const,
          needs_reason: false,
          blocked_by: "The review didn't finish. Start it again.",
        },
      ],
    };
    await stubBoard(page, failed);
    await page.route(
      `**/stub-api/engine/reviews/${ENGINE_ID}/findings`,
      (route) => route.abort(),
    );
    let starts = 0;
    await page.route("**/stub-api/content/c1/reviews", (route) => {
      starts += 1;
      return route.fulfill({ status: 201, json: CONTENT.latest_review });
    });
    await page.goto("/content/c1/review");
    await expect(bar(page)).toContainText("didn't finish");

    // The new run has its own id, so findings from the failed one can't reappear.
    const NEW_ID = "rev-demo-new";
    let oldOpens = 0;
    await page.route(`**/stub-api/engine/reviews/${ENGINE_ID}/findings`, (route) => {
      oldOpens += 1;
      return route.abort();
    });
    await stubReview(page, {
      content: {
        ...CONTENT,
        latest_review: { ...CONTENT.latest_review, engine_review_id: NEW_ID },
      },
    });
    await page.route(`**/stub-api/engine/reviews/${NEW_ID}/chunks`, (route) =>
      route.fulfill({ json: CHUNKS }),
    );
    await page.route(`**/stub-api/engine/reviews/${NEW_ID}/findings`, (route) =>
      route.fulfill({ contentType: "text/event-stream", body: stream(FINDINGS) }),
    );
    await bar(page).getByRole("button", { name: "Start review again" }).click();

    await expect(findingCards(page)).toHaveCount(FINDINGS.length);
    expect(starts).toBe(1);
    expect(oldOpens).toBe(0);
  });

  test("manager and legal are warned about hidden text a reviewer let through", async ({
    page,
  }) => {
    await stubReview(page);
    await stubBoard(page, { ...boardFor(), state: "manager_approval", hidden_overridden: true });
    await page.goto("/content/c1/review");

    await expect(bar(page)).toContainText("A reviewer let hidden text through");
  });

  test("a refused restart says why", async ({ page }) => {
    await stubReview(page);
    await stubBoard(page, { ...boardFor(), state: "ai_review", can_restart: true });
    await page.route("**/stub-api/content/c1/reviews", (route) =>
      route.fulfill({
        status: 409,
        json: { detail: "This review is still running." },
      }),
    );
    await page.goto("/content/c1/review");

    await bar(page).getByRole("button", { name: "Start review again" }).click();

    await expect(bar(page).getByRole("alert")).toHaveText(
      "This review is still running.",
    );
  });

  test("a dropped stream is reopened and catches up", async ({ page }) => {
    await stubReview(page);
    let opens = 0;
    await page.route(
      `**/stub-api/engine/reviews/${ENGINE_ID}/findings`,
      (route) => {
        opens += 1;
        return opens === 1
          ? route.abort()
          : route.fulfill({
              contentType: "text/event-stream",
              body: stream(FINDINGS),
            });
      },
    );
    await page.goto("/content/c1/review");

    await expect(findingCards(page)).toHaveCount(FINDINGS.length);
    await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
  });

  test("offers no moves on finished content", async ({ page }) => {
    await stubReview(page);
    await stubBoard(page, { ...boardFor(), state: "published" });
    await page.goto("/content/c1/review");

    await expect(bar(page)).toContainText("Status: Published");
    await expect(bar(page).getByRole("button")).toHaveCount(0);
  });

  test("a board that won't load says so", async ({ page }) => {
    await stubReview(page);
    await page.route("**/stub-api/workflow/content/c1/board", (route) =>
      route.fulfill({ status: 500, json: {} }),
    );
    await page.goto("/content/c1/review");

    await expect(page.locator("main").getByRole("alert").first()).toBeVisible();
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

  test("an open fix and trace have no violations", async ({ page }) => {
    await stubReview(page);
    await stubFixes(page, [{ json: fixFor(1) }]);
    await page.route("**/stub-api/engine/verdicts/*/replay", (route) =>
      route.fulfill({ json: REPLAY }),
    );
    await page.goto("/content/c1/review");

    const found = card(page, "retired name");
    await found.getByRole("button", { name: "Suggest fix" }).click();
    await found.getByRole("button", { name: "Replay" }).click();
    await found.getByText("Why was this flagged?").click();
    await expect(found.locator("ins")).toBeVisible();
    await expect(found.getByRole("status")).toBeVisible();

    await expectNoAccessibilityViolations(page);
  });

  test("open reason forms have no violations", async ({ page }) => {
    await stubReview(page);
    await stubBoard(page, {
      ...boardFor(),
      moves: [{ to: "rejected", needs_reason: true, blocked_by: null }],
    });
    await page.goto("/content/c1/review");

    const low = findingCards(page)
      .filter({ has: page.getByRole("button", { name: "Override" }) })
      .first();
    await low.getByRole("button", { name: "Override" }).click();
    await page.getByRole("button", { name: "Reject" }).click();
    await expect(page.getByLabel("Why: reject?")).toBeVisible();

    await expectNoAccessibilityViolations(page);
  });

  test("a failed fix on a selected card has no violations", async ({
    page,
  }) => {
    await stubReview(page);
    await stubFixes(page, [
      { status: 422, json: { detail: "No safe fix found; marked for review" } },
    ]);
    await page.goto("/content/c1/review");

    await cardFor(page, "retired name").click();
    const found = card(page, "retired name");
    await found.getByRole("button", { name: "Suggest fix" }).click();
    await expect(found.getByRole("alert")).toBeVisible();

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
