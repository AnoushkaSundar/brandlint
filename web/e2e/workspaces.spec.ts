import { spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

// Two workspaces, two browsers, one real stack: sign up, set up, run the CLI, waive in the
// web app, and check that neither workspace can see the other. Needs the stack from
// demo/run_e2e.sh (API on E2E_API, web on E2E_WEB, mock engine, Row-Level Security on).
const API = process.env.E2E_API ?? "http://localhost:8000";
const ROOT = path.resolve(__dirname, "..", "..");
const PASSWORD = "e2e-password-123";
const stamp = Date.now().toString(36);

async function signUp(page: Page, workspace: string, who: string) {
  await page.goto("/login");
  await page.locator("#workspace_name").fill(workspace);
  await page.locator("#name").fill(who);
  await page.locator("#signup_email").fill(`${who.toLowerCase()}-${stamp}@e2e.example`);
  await page.locator("#signup_password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/content$/);
}

function runCli(token: string, repo: string) {
  return spawnSync(
    process.env.E2E_PYTHON ?? "python",
    ["-m", "brandlint_cli", "check", "--root", repo, "--server", API, "--format", "json", "--timeout", "120"],
    {
      env: {
        ...process.env,
        PYTHONPATH: path.join(ROOT, "cli", "src"),
        BRANDLINT_TOKEN: token,
        GITHUB_REPOSITORY: "acme/site",
        GITHUB_SHA: "e2e",
      },
      encoding: "utf8",
    },
  );
}

test("two workspaces, end to end", async ({ browser }) => {
  const acme = await browser.newContext();
  const beta = await browser.newContext();
  const a = await acme.newPage();
  const b = await beta.newPage();

  // --- Acme signs up and sets itself up ---------------------------------------------
  await signUp(a, `Acme ${stamp}`, "Ada");
  await expect(a.getByText(`Acme ${stamp}`, { exact: true })).toBeVisible();
  await expect(a.getByText(/sandbox workspace/)).toBeVisible(); // it expires
  const checklist = a.getByRole("region", { name: `Set up Acme ${stamp}` });
  await expect(checklist).toBeVisible();
  await checklist.getByRole("button", { name: "Load sample guidelines" }).click();
  await expect(checklist.getByRole("button", { name: "Load sample guidelines" })).toHaveCount(0);

  // A reviewer for the waiver, added in the web app.
  await a.goto("/people");
  await a.locator("#person-name").fill("Lena");
  await a.locator("#person-email").fill(`lena-${stamp}@e2e.example`);
  await a.locator("#person-role").selectOption("reviewer");
  await a.locator("#person-password").fill(PASSWORD);
  await a.getByRole("button", { name: "Add person" }).click();
  await expect(a.getByText(`lena-${stamp}@e2e.example`)).toBeVisible();

  // A service token, shown once.
  await a.goto("/ci/settings");
  await a.locator("#token-name").fill("GitHub Action");
  await a.getByRole("button", { name: "Create token" }).click();
  const shown = a.locator("code").filter({ hasText: /^bl_[A-Za-z0-9_-]{30,}$/ });
  await expect(shown).toBeVisible();
  const token = (await shown.textContent())!.trim();
  await a.getByRole("button", { name: "I've copied it" }).click();
  await expect(a.getByText(token)).toHaveCount(0);

  // --- The CLI checks a repo of copy, as CI would -------------------------------------
  const repo = path.join(mkdtempSync(path.join(tmpdir(), "brandlint-e2e-")), "repo");
  cpSync(path.join(ROOT, "integrations", "fixtures", "repo"), repo, { recursive: true });
  const config = path.join(repo, ".brandlint.yml");
  writeFileSync(config, readFileSync(config, "utf8").replace(/^server:.*\n/m, ""));
  const first = runCli(token, repo);
  expect(first.status, first.stdout + first.stderr).toBe(1);
  expect(first.stdout + first.stderr).not.toContain(token);
  const run = JSON.parse(first.stdout).runs[0];

  // --- Acme reads the run in the web app ------------------------------------------------
  const runPage = `/ci/runs/${run.id}`;
  await a.goto(runPage);
  await expect(a.getByRole("status").filter({ hasText: "Failed" })).toBeVisible();
  await expect(a.getByText("Blocks the run").first()).toBeVisible();

  // --- Beta signs up in its own browser and can see none of it --------------------------
  await signUp(b, `Beta ${stamp}`, "Bea");
  await b.goto(runPage);
  await expect(b.getByRole("heading", { level: 1 })).toHaveText("Run not found");
  await expect(b.getByText(run.files[0].path)).toHaveCount(0);
  const asBeta = await beta.request.get(`${API}/ci/runs/${run.id}`);
  expect(asBeta.status()).toBe(404);
  const content = await beta.request.get(`${API}/content/${run.files[0].content_id}`);
  expect(content.status()).toBe(404);
  await b.goto("/people");
  await expect(b.getByText(`bea-${stamp}@e2e.example`)).toBeVisible();
  await expect(b.getByText(`lena-${stamp}@e2e.example`)).toHaveCount(0);

  // --- Lena, Acme's reviewer, waives what blocks, in her own session --------------------
  const lenaContext = await browser.newContext();
  const lena = await lenaContext.newPage();
  await lena.goto("/login");
  await lena.locator("#email").fill(`lena-${stamp}@e2e.example`);
  await lena.locator("#password").fill(PASSWORD);
  await lena.getByRole("button", { name: "Sign in" }).click();
  await expect(lena).toHaveURL(/\/content$/);
  await lena.goto(runPage);
  await expect(lena.getByRole("status").filter({ hasText: "Failed" })).toBeVisible();
  let waived = 0;
  for (const file of run.files) {
    for (const found of file.findings) {
      if (!found.blocking) continue;
      const response = await lenaContext.request.post(
        `${API}/workflow/content/${file.content_id}/findings/${found.id}/decisions`,
        { data: { action: found.verdict === "UNSURE" ? "resolve" : "override", reason: "Approved by brand review." } },
      );
      expect(response.status()).toBe(201);
      waived += 1;
    }
  }
  expect(waived).toBeGreaterThan(0);

  // --- The same CLI run now passes, with no new run, and the page says so ----------------
  const second = runCli(token, repo);
  expect(second.status, second.stdout + second.stderr).toBe(0);
  expect(JSON.parse(second.stdout).runs[0].id).toBe(run.id);
  await a.goto(runPage);
  await expect(a.getByRole("status").filter({ hasText: "Passed" })).toBeVisible();

  // --- The CI insights count it, for Acme only ------------------------------------------
  const insights = await acme.request.get(`${API}/insights/ci`);
  expect(insights.status()).toBe(200);
  expect((await insights.json()).runs_30d).toBeGreaterThanOrEqual(1);
  expect((await (await beta.request.get(`${API}/insights/ci`)).json()).runs_30d).toBe(0);

  await acme.close();
  await beta.close();
  await lenaContext.close();
});
