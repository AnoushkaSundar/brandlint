import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import type { Role } from "../lib/contracts";
import type { AuditPage, Comment, History, Queue } from "../lib/reviewDesk";

const WCAG_22_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const WHEN = "2026-11-06T12:00:00Z";

const CONTENT = {
  id: "c1",
  title: "First week guide",
  channel: "blog",
  source: "in-house",
  data_class: "public",
  state: "reviewer_check",
  creator_id: "u1",
  created_at: WHEN,
};

const QUEUE: Queue = {
  items: [
    {
      content_id: "c1",
      title: "First week guide",
      channel: "blog",
      state: "resolving",
      finding_id: "f1",
      kind: "unsure",
      severity: "medium",
      check: "tone",
      explanation: "This might be too pushy.",
      rule_id: "R-TONE-01",
      fact_ids: [],
      cited_text: "Be warm, never pushy.",
      reason: null,
      fix_text: null,
    },
    {
      content_id: "c2",
      title: "Launch post",
      channel: "linkedin",
      state: "resolving",
      finding_id: "f2",
      kind: "override",
      severity: "low",
      check: "terminology",
      explanation: "This uses a banned word.",
      rule_id: "R-TERM-03",
      fact_ids: [],
      cited_text: "Say new hire.",
      reason: "It's a direct quote",
      fix_text: null,
    },
    {
      content_id: "c4",
      title: "Edited piece",
      channel: "blog",
      state: "resolving",
      finding_id: "f4",
      kind: "fix",
      severity: "low",
      check: "terminology",
      explanation: "This uses an old name.",
      rule_id: "R-TERM-02",
      fact_ids: ["F-001"],
      cited_text: "The product is Tarnhollow Landing.",
      reason: null,
      fix_text: "The Landing app",
    },
  ],
  ready: [{ ...CONTENT, id: "c3", title: "Ready piece" }] as Queue["ready"],
  unavailable: [],
};

async function signedInAs(page: Page, role: Role) {
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

test.describe("review queue", () => {
  test.beforeEach(async ({ page }) => {
    await signedInAs(page, "reviewer");
  });

  test("lists decisions with the reason and a link to the piece", async ({
    page,
  }) => {
    await page.route("**/stub-api/workflow/queue", (route) =>
      route.fulfill({ json: QUEUE }),
    );
    await page.goto("/queue");

    const items = page.getByRole("region", { name: "Decisions needed" });
    await expect(items.getByRole("listitem")).toHaveCount(3);
    await expect(items.getByRole("listitem").first()).toContainText(
      "Needs a decision",
    );
    await expect(items.getByRole("listitem").nth(1)).toContainText(
      "Creator's reason: It's a direct quote",
    );
    await expect(items.getByRole("listitem").last()).toContainText(
      "Fix to sign off",
    );
    await expect(items.getByRole("listitem").last()).toContainText(
      "Wording: The Landing app",
    );
    await expect(
      items.getByRole("link", { name: "First week guide" }),
    ).toHaveAttribute("href", "/content/c1/review");
  });

  test("shows the source of every item", async ({ page }) => {
    await page.route("**/stub-api/workflow/queue", (route) =>
      route.fulfill({ json: QUEUE }),
    );
    await page.goto("/queue");

    const last = page
      .getByRole("region", { name: "Decisions needed" })
      .getByRole("listitem")
      .last();
    await expect(last.locator("blockquote")).toHaveText(
      "The product is Tarnhollow Landing.",
    );
    await expect(last.locator("figcaption")).toHaveText("R-TERM-02 · F-001");
  });

  test("names a finding only a reviewer can clear", async ({ page }) => {
    await page.route("**/stub-api/workflow/queue", (route) =>
      route.fulfill({
        json: {
          ...QUEUE,
          items: [{ ...QUEUE.items[0], kind: "needs_override" }],
        },
      }),
    );
    await page.goto("/queue");

    await expect(page.locator("main")).toContainText(
      "Only a reviewer can clear this",
    );
  });

  test("says when a piece couldn't load and keeps the rest", async ({ page }) => {
    await page.route("**/stub-api/workflow/queue", (route) =>
      route.fulfill({ json: { ...QUEUE, unavailable: ["Broken piece"] } }),
    );
    await page.goto("/queue");

    await expect(page.locator("main").getByRole("alert")).toContainText(
      "Broken piece",
    );
    await expect(
      page.getByRole("region", { name: "Decisions needed" }),
    ).toBeVisible();
  });

  test("lists pieces ready for review", async ({ page }) => {
    await page.route("**/stub-api/workflow/queue", (route) =>
      route.fulfill({ json: QUEUE }),
    );
    await page.goto("/queue");

    await expect(
      page
        .getByRole("region", { name: "Ready for review" })
        .getByRole("link", { name: "Ready piece" }),
    ).toHaveAttribute("href", "/content/c3/review");
  });

  test("says when nothing is waiting", async ({ page }) => {
    await page.route("**/stub-api/workflow/queue", (route) =>
      route.fulfill({ json: { items: [], ready: [], unavailable: [] } }),
    );
    await page.goto("/queue");

    await expect(page.locator("main")).toContainText("Nothing is waiting");
  });

  test("reports a failure", async ({ page }) => {
    await page.route("**/stub-api/workflow/queue", (route) =>
      route.fulfill({
        status: 403,
        json: { detail: "Not allowed for your role" },
      }),
    );
    await page.goto("/queue");

    await expect(page.locator("main").getByRole("alert")).toHaveText(
      "Not allowed for your role",
    );
  });

  test("has no accessibility violations", async ({ page }) => {
    await page.route("**/stub-api/workflow/queue", (route) =>
      route.fulfill({ json: QUEUE }),
    );
    await page.goto("/queue");
    await expect(
      page.getByRole("region", { name: "Ready for review" }),
    ).toBeVisible();

    await noViolations(page);
  });
});

test.describe("approvals", () => {
  const ITEMS = [
    { ...CONTENT, id: "a", title: "For the manager", state: "manager_approval" },
    { ...CONTENT, id: "b", title: "For legal", state: "legal_signoff" },
    { ...CONTENT, id: "c", title: "Still in review", state: "reviewer_check" },
  ];

  test("a manager sees what's waiting for approval", async ({ page }) => {
    await signedInAs(page, "manager");
    await page.route("**/stub-api/content", (route) =>
      route.fulfill({ json: ITEMS }),
    );
    await page.goto("/approvals");

    const list = page.locator("main").getByRole("listitem");
    await expect(list).toHaveCount(1);
    await expect(list).toContainText("For the manager");
  });

  test("legal sees what's waiting for sign-off", async ({ page }) => {
    await signedInAs(page, "legal");
    await page.route("**/stub-api/content", (route) =>
      route.fulfill({ json: ITEMS }),
    );
    await page.goto("/approvals");

    const list = page.locator("main").getByRole("listitem");
    await expect(list).toHaveCount(1);
    await expect(list).toContainText("For legal");
  });

  test("says when nothing is waiting", async ({ page }) => {
    await signedInAs(page, "manager");
    await page.route("**/stub-api/content", (route) =>
      route.fulfill({ json: [] }),
    );
    await page.goto("/approvals");

    await expect(page.locator("main")).toContainText("Nothing is waiting");
  });
});

test.describe("audit log", () => {
  const entry = (index: number) => ({
    id: `e${index}`,
    actor: "Lena Fischer",
    role: "reviewer",
    action: "decision:confirm_override",
    target_type: "finding",
    target_id: "f1",
    before: { status: "override_pending" },
    after: { status: "override_confirmed" },
    rulebook_version: 1,
    created_at: WHEN,
  });
  const PAGE: AuditPage = { total: 30, items: [entry(1)] };

  async function stubAudit(page: Page, seen: URL[] = []) {
    await page.route("**/stub-api/workflow/audit*", (route) => {
      seen.push(new URL(route.request().url()));
      return route.fulfill({ json: PAGE });
    });
    return seen;
  }

  test.beforeEach(async ({ page }) => {
    await signedInAs(page, "manager");
  });

  test("shows who did what", async ({ page }) => {
    await stubAudit(page);
    await page.goto("/audit");

    const row = page.getByRole("row").nth(1);
    await expect(row).toContainText("Lena Fischer");
    await expect(row).toContainText("decision:confirm_override");
    await expect(row).toContainText("override_pending → override_confirmed");
  });

  test("filters on the server and goes back to the first page", async ({
    page,
  }) => {
    const seen = await stubAudit(page);
    await page.goto("/audit");
    await page.getByRole("button", { name: "Older" }).click();
    await expect(page.locator("main")).toContainText("26–30 of 30");

    await page.getByLabel("Show").selectOption("decision:");
    await page.getByLabel("Role").selectOption("reviewer");

    await expect(page.locator("main")).toContainText("1–25 of 30");
    const last = seen.at(-1) as URL;
    expect(last.searchParams.get("action")).toBe("decision:");
    expect(last.searchParams.get("role")).toBe("reviewer");
    expect(last.searchParams.get("offset")).toBe("0");
  });

  test("pages through the log", async ({ page }) => {
    await stubAudit(page);
    await page.goto("/audit");

    await expect(page.getByRole("button", { name: "Newer" })).toBeDisabled();
    await page.getByRole("button", { name: "Older" }).click();

    await expect(page.locator("main")).toContainText("26–30 of 30");
    await expect(page.getByRole("button", { name: "Older" })).toBeDisabled();
  });

  test("says when a filter matches nothing", async ({ page }) => {
    await page.route("**/stub-api/workflow/audit*", (route) =>
      route.fulfill({ json: { total: 0, items: [] } }),
    );
    await page.goto("/audit");

    await expect(page.locator("main")).toContainText("Nothing matches");
  });

  test("has no accessibility violations", async ({ page }) => {
    await stubAudit(page);
    await page.goto("/audit");
    await expect(page.getByRole("table")).toBeVisible();

    await noViolations(page);
  });
});

test.describe("content history", () => {
  const versions = [
    { version: 2, text: "Say new hires today" },
    { version: 1, text: "Say newbies today" },
  ].map(({ version, text }) => ({
    id: `v${version}`,
    content_id: "c1",
    version,
    text,
    file_name: null,
    created_by: "u1",
    created_at: WHEN,
  }));
  const DETAIL = { ...CONTENT, versions, latest_review: null };
  const HISTORY: History = {
    states: [
      {
        from_state: "reviewer_check",
        to_state: "resolving",
        actor: "Lena Fischer",
        reason: "Reword the claim",
        created_at: WHEN,
      },
    ],
    decisions: [
      {
        finding_id: "f1",
        action: "override",
        actor: "Sam Okafor",
        role: "creator",
        reason: "A direct quote",
        version: 1,
        created_at: WHEN,
      },
    ],
    stamp: null,
  };

  async function stubDetail(page: Page, history = HISTORY, detail = DETAIL) {
    await signedInAs(page, "reviewer");
    await page.route("**/stub-api/content/c1", (route) =>
      route.fulfill({ json: detail }),
    );
    await page.route("**/stub-api/workflow/content/c1/history", (route) =>
      route.fulfill({ json: history }),
    );
  }

  const section = (page: Page) =>
    page.getByRole("region", { name: "Review record" });

  test("compares the two newest versions by default", async ({ page }) => {
    await stubDetail(page);
    await page.goto("/content/c1");

    await expect(section(page).locator("del")).toContainText("newbies");
    await expect(section(page).locator("ins").first()).toContainText("new");
  });

  test("any two versions can be compared", async ({ page }) => {
    await stubDetail(page);
    await page.goto("/content/c1");

    await section(page).getByLabel("With").selectOption("1");

    await expect(section(page).locator("del")).toHaveCount(0);
    await expect(section(page).locator("ins")).toHaveCount(0);
  });

  test("a single version has nothing to compare", async ({ page }) => {
    await stubDetail(page, HISTORY, { ...DETAIL, versions: [versions[1]] });
    await page.goto("/content/c1");

    await expect(section(page)).toContainText("A direct quote");
    await expect(section(page).getByLabel("Compare")).toHaveCount(0);
  });

  test("a file with no text says it can't be compared", async ({ page }) => {
    await stubDetail(page, HISTORY, {
      ...DETAIL,
      versions: [{ ...versions[0], text: "" }, versions[1]],
    });
    await page.goto("/content/c1");

    await expect(section(page)).toContainText("no text to compare");
  });

  test("lists decisions and moves with their reasons", async ({ page }) => {
    await stubDetail(page);
    await page.goto("/content/c1");

    await expect(section(page)).toContainText(
      "Overrode on version 1: Sam Okafor",
    );
    await expect(section(page)).toContainText("A direct quote");
    await expect(section(page)).toContainText("Lena Fischer");
    await expect(section(page)).toContainText("Reword the claim");
  });

  test("published content is stamped", async ({ page }) => {
    await stubDetail(page, {
      ...HISTORY,
      stamp: {
        version: 2,
        rulebook_version: 1,
        approvers: ["Lena Fischer", "Marcus Bell"],
        published_at: WHEN,
      },
    });
    await page.goto("/content/c1");

    await expect(section(page)).toContainText("version 2");
    await expect(section(page)).toContainText("rulebook version 1");
    await expect(section(page)).toContainText(
      "Approved by Lena Fischer, Marcus Bell",
    );
  });

  test("has no accessibility violations", async ({ page }) => {
    await stubDetail(page);
    await page.goto("/content/c1");
    await expect(section(page).locator("del")).toBeVisible();

    await noViolations(page);
  });
});

test.describe("comments", () => {
  const ENGINE_ID = "rev-1";
  const COMMENT: Comment = {
    id: "k1",
    content_version_id: "v1",
    finding_id: null,
    span: null,
    parent_id: null,
    author: "Lena Fischer",
    body: "Could @reviewer check this?",
    mentions: ["Test reviewer"],
    created_at: WHEN,
  };
  const REPLY: Comment = {
    ...COMMENT,
    id: "k2",
    parent_id: "k1",
    author: "Sam Okafor",
    body: "Looks fine",
    mentions: [],
  };
  const FINDING = {
    id: "f1",
    review_id: ENGINE_ID,
    content_version_id: "v1",
    unit_type: "chunk",
    spans: [],
    check: "tone",
    tier: 0,
    verdict: "VIOLATION",
    severity: "low",
    confidence: 1,
    fact_ids: [],
    cited_text: "Be friendly.",
    explanation: "A finding to talk about.",
    trace: { steps: [], sources: [] },
    ai_generated: false,
    models_used: [],
    fix_available: false,
    status: "open",
  };

  async function stubScreen(page: Page, initial: Comment[] = []) {
    let comments = initial;
    const posted: Record<string, unknown>[] = [];
    await signedInAs(page, "reviewer");
    await page.route("**/stub-api/content/c1", (route) =>
      route.fulfill({
        json: {
          ...CONTENT,
          versions: [
            {
              id: "v1",
              content_id: "c1",
              version: 1,
              text: "",
              file_name: null,
              created_by: "u1",
              created_at: WHEN,
            },
          ],
          latest_review: {
            id: "r1",
            content_version_id: "v1",
            engine_review_id: ENGINE_ID,
            channel: "blog",
            rulebook_version: 1,
            created_at: WHEN,
          },
        },
      }),
    );
    await page.route(`**/stub-api/engine/reviews/${ENGINE_ID}/chunks`, (route) =>
      route.fulfill({ json: [] }),
    );
    await page.route(
      `**/stub-api/engine/reviews/${ENGINE_ID}/findings`,
      (route) =>
        route.fulfill({
          contentType: "text/event-stream",
          body: `event: finding\ndata: ${JSON.stringify(FINDING)}\n\nevent: done\ndata: {}\n\n`,
        }),
    );
    await page.route("**/stub-api/admin/rulebook*", (route) =>
      route.fulfill({ json: [] }),
    );
    await page.route("**/stub-api/memory/precedents*", (route) =>
      route.fulfill({ json: [] }),
    );
    await page.route("**/stub-api/workflow/content/c1/board", (route) =>
      route.fulfill({
        json: {
          state: "resolving",
          legal_required: false,
          findings: [],
          moves: [],
        },
      }),
    );
    await page.route("**/stub-api/workflow/content/c1/comments", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({ json: comments });
      }
      const body = route.request().postDataJSON();
      posted.push(body);
      comments = [
        ...comments,
        {
          ...COMMENT,
          id: `k${comments.length + 10}`,
          author: "Test reviewer",
          mentions: [],
          ...body,
        },
      ];
      return route.fulfill({ status: 201, json: comments });
    });
    return posted;
  }

  const onVersion = (page: Page) =>
    page.getByRole("region", { name: "Comments on this version" });

  test("a comment on the version is posted", async ({ page }) => {
    const posted = await stubScreen(page);
    await page.goto("/content/c1/review");

    await onVersion(page).getByLabel("Add a comment").fill("Nice work");
    await onVersion(page).getByRole("button", { name: "Post comment" }).click();

    await expect(onVersion(page)).toContainText("Nice work");
    expect(posted[0]).toMatchObject({
      body: "Nice work",
      content_version_id: "v1",
      finding_id: null,
      parent_id: null,
    });
  });

  test("a blank comment can't be sent", async ({ page }) => {
    await stubScreen(page);
    await page.goto("/content/c1/review");

    await expect(
      onVersion(page).getByRole("button", { name: "Post comment" }),
    ).toBeDisabled();
  });

  test("a comment on a finding stays on that finding", async ({ page }) => {
    const posted = await stubScreen(page);
    await page.goto("/content/c1/review");

    const card = page.getByRole("article");
    await card.getByText("Comments (0)").click();
    await card.getByLabel("Comment on this finding").fill("About this one");
    await card.getByRole("button", { name: "Post comment" }).click();

    await expect(card).toContainText("About this one");
    await expect(onVersion(page)).not.toContainText("About this one");
    expect(posted[0]).toMatchObject({ finding_id: "f1" });
  });

  test("the comment count shows on the card", async ({ page }) => {
    await stubScreen(page, [{ ...COMMENT, finding_id: "f1" }]);
    await page.goto("/content/c1/review");

    await expect(page.getByRole("article")).toContainText("Comments (1)");
  });

  test("replies sit under their comment", async ({ page }) => {
    await stubScreen(page, [COMMENT, REPLY]);
    await page.goto("/content/c1/review");

    const nested = onVersion(page).getByRole("list").getByRole("list");
    await expect(nested).toContainText("Looks fine");
    await expect(onVersion(page)).toContainText("Mentions Test reviewer");
  });

  test("a reply is linked to its parent", async ({ page }) => {
    const posted = await stubScreen(page, [COMMENT]);
    await page.goto("/content/c1/review");

    await onVersion(page)
      .getByRole("button", { name: "Reply to Lena Fischer" })
      .click();
    await onVersion(page).getByLabel("Reply to Lena Fischer").fill("Agreed");
    await onVersion(page).getByRole("button", { name: "Send reply" }).click();

    await expect(onVersion(page)).toContainText("Agreed");
    expect(posted[0]).toMatchObject({ parent_id: "k1", body: "Agreed" });
  });

  test("a failed comment keeps what was typed", async ({ page }) => {
    await stubScreen(page);
    await page.route("**/stub-api/workflow/content/c1/comments", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: [] })
        : route.fulfill({ status: 500, json: { detail: "That failed." } }),
    );
    await page.goto("/content/c1/review");

    const field = onVersion(page).getByLabel("Add a comment");
    await field.fill("Don't lose me");
    await onVersion(page).getByRole("button", { name: "Post comment" }).click();

    await expect(onVersion(page).getByRole("alert")).toHaveText("That failed.");
    await expect(field).toHaveValue("Don't lose me");
  });

  test("has no accessibility violations", async ({ page }) => {
    await stubScreen(page, [COMMENT, REPLY]);
    await page.goto("/content/c1/review");
    await expect(onVersion(page)).toContainText("Looks fine");

    await noViolations(page);
  });
});
