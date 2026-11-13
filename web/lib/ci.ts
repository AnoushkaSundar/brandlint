import { apiFetch } from "@/lib/api";
import type { CIResult, CIRunState, CIRunStatus, Severity } from "@/lib/contracts";

// The CI/CD integration (docs/ci-integration.md). Off until the API has
// CI_INTEGRATION_ENABLED=true and the web build has NEXT_PUBLIC_CI_ENABLED=true.

export type CIRunSummary = {
  id: string;
  repo: string;
  pr: number | null;
  sha: string;
  state: CIRunState;
  result: CIResult | null;
  created_at: string;
  finished_at: string | null;
  files: number;
};

export function getCIRuns(): Promise<CIRunSummary[]> {
  return apiFetch<CIRunSummary[]>("/ci/runs");
}

export function getCIRun(id: string): Promise<CIRunStatus> {
  return apiFetch<CIRunStatus>(`/ci/runs/${encodeURIComponent(id)}`);
}

export type PolicySettings = {
  severity_threshold: Severity;
  fail_on_unsure: boolean;
  ignore_rules: string[];
  max_waiting_minutes: number;
};

export function getCIPolicy(): Promise<PolicySettings> {
  return apiFetch<PolicySettings>("/ci/policy");
}

export function saveCIPolicy(policy: PolicySettings): Promise<PolicySettings> {
  return apiFetch<PolicySettings>("/ci/policy", {
    method: "PUT",
    body: JSON.stringify(policy),
  });
}

export type ServiceToken = {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
};

export type CreatedToken = ServiceToken & {
  // The only time the token is shown.
  token: string;
};

export function getTokens(): Promise<ServiceToken[]> {
  return apiFetch<ServiceToken[]>("/ci/tokens");
}

export function createToken(
  name: string,
  expiresInDays: number | null,
): Promise<CreatedToken> {
  return apiFetch<CreatedToken>("/ci/tokens", {
    method: "POST",
    body: JSON.stringify({ name, expires_in_days: expiresInDays }),
  });
}

export function revokeToken(id: string): Promise<void> {
  return apiFetch<void>(`/ci/tokens/${id}`, { method: "DELETE" });
}

export const RESULT_LABELS: Record<CIResult, string> = {
  pass: "Passed",
  fail: "Failed",
};

export const STATE_LABELS: Record<CIRunState, string> = {
  queued: "Queued",
  running: "Checking",
  done: "Done",
  error: "Couldn't check",
};

// What a person puts in their workflow. The action ships in this repo's
// integrations/github-action folder; pin it by commit in a real repo.
export const EXAMPLE_WORKFLOW = `name: BrandLint
on:
  pull_request:
permissions:
  contents: read
  pull-requests: write
concurrency:
  group: brandlint-\${{ github.event.pull_request.number }}
  cancel-in-progress: true
jobs:
  copy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: <owner>/brandlint/integrations/github-action@<commit-sha>
        with:
          server: https://your-brandlint.example/api
        env:
          BRANDLINT_TOKEN: \${{ secrets.BRANDLINT_TOKEN }}
`;

export type CIInsights = {
  runs_30d: number;
  runs_7d: number;
  by_result: { pass: number; fail: number; error: number; running: number };
  average_seconds: number | null;
  failure_reasons: { reason: string; count: number }[];
  tokens: {
    name: string;
    prefix: string;
    runs_7d: number;
    last_used_at: string | null;
    revoked: boolean;
  }[];
};

export function getCIInsights(): Promise<CIInsights> {
  return apiFetch<CIInsights>("/insights/ci");
}
