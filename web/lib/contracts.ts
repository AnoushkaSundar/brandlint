// TypeScript mirror of api/app/contracts (docs/contracts.md). Frozen after block 2:
// any change needs its own contracts/vN PR that both people approve.

export const ROLES = [
  "creator",
  "reviewer",
  "manager",
  "legal",
  "admin",
] as const;

export type Role = (typeof ROLES)[number];

export type Severity = "low" | "medium" | "high" | "critical";

export type Verdict = "VIOLATION" | "UNSURE" | "PASS";

export type CheckType =
  | "tone"
  | "terminology"
  | "messaging"
  | "claim"
  | "visual"
  | "accessibility"
  | "hidden_content"
  | "required_element"
  | "tone_drift";

export type UnitType = "chunk" | "claim" | "document";

export type DataClass = "public" | "internal" | "confidential" | "restricted";

export type ContentState =
  | "draft"
  | "ai_review"
  | "resolving"
  | "reviewer_check"
  | "manager_approval"
  | "legal_signoff"
  | "published"
  | "rejected";

export type FindingStatus =
  | "open"
  | "fix_accepted"
  | "fix_edited"
  | "override_pending"
  | "override_confirmed"
  | "override_rejected"
  | "resolved";

export type RuleType = "deterministic" | "judgment" | "must_include";

export type RuleStatus = "draft" | "approved" | "retired";

export type DecisionAction =
  | "accept_fix"
  | "edit_fix"
  | "override"
  | "confirm_override"
  | "reject_override"
  | "resolve";

export type AssetKind = "logo" | "palette" | "image" | "font";

export type ProposalKind = "amendment" | "anchor" | "term" | "severity";

export type ProposalStatus = "pending" | "approved" | "rejected";

export type Span = {
  chunk_id: string;
  start: number;
  end: number;
};

export type TraceStep = {
  tool: string;
  input_summary: string;
  output_summary: string;
};

export type Trace = {
  steps: TraceStep[];
  sources: string[];
  model?: string | null;
};

export type Vote = {
  variants: number;
  agree: number;
  split: boolean;
};

export type Finding = {
  id: string;
  review_id: string;
  content_version_id: string;
  unit_type: UnitType;
  spans: Span[];
  check: CheckType;
  tier: 0 | 1 | 2;
  verdict: Verdict;
  severity: Severity;
  confidence: number;
  rule_id?: string | null;
  rule_version?: number | null;
  fact_ids: string[];
  cited_text: string;
  explanation: string;
  trace: Trace;
  ai_generated: boolean;
  models_used: string[];
  vote?: Vote | null;
  fix_available: boolean;
  status: FindingStatus;
};

export type Rule = {
  id: string;
  version: number;
  type: RuleType;
  text: string;
  clause_ref: string;
  severity: Severity;
  channel_scope: string[];
  status: RuleStatus;
  supersedes?: string | null;
  required_text?: string | null;
};

export type Fact = {
  id: string;
  statement: string;
  value: string;
  source_doc: string;
  owner: string;
  valid_until?: string | null;
  data_class: DataClass;
  version: number;
};

export type Term = {
  id: string;
  preferred: string;
  banned: string[];
  renamed_from?: string | null;
  rule_id?: string | null;
  rule_version?: number | null;
};

export type Asset = {
  id: string;
  kind: AssetKind;
  file_ref: string;
  meta: Record<string, unknown>;
};

export type Decision = {
  id: string;
  finding_id: string;
  actor_id: string;
  role: Role;
  action: DecisionAction;
  reason?: string | null;
  created_at: string;
};

export type Gap = {
  id: string;
  review_id: string;
  check: CheckType;
  text: string;
  explanation: string;
  created_at: string;
};

export type FixSuggestion = {
  finding_id: string;
  original: string;
  suggested: string;
  diff: string;
  attempt: 1 | 2;
};

export type Precedent = {
  decision_id: string;
  rule_id: string;
  rule_version: number;
  channel: string;
  reason: string;
  reviewer: string;
  date: string;
};

export type ProposalEvidence = {
  count: number;
  examples: Span[];
};

export type ProposalEval = {
  passed: boolean;
  precision: number;
  recall: number;
};

export type ChunkKind = "heading" | "paragraph" | "image";

export type Chunk = {
  id: string;
  content_version_id: string;
  ordinal: number;
  kind: ChunkKind;
  text: string;
  content_hash: string;
  data_class: DataClass;
  style?: Record<string, unknown> | null;
};

export type Proposal = {
  id: string;
  rule_id: string;
  kind: ProposalKind;
  current: string;
  suggested: string;
  evidence: ProposalEvidence;
  eval?: ProposalEval | null;
  status: ProposalStatus;
};

// Workspaces (GET /orgs/current). The demo org is Tarnhollow; a sandbox is a visitor's own.
export type OrgKind = "demo" | "sandbox";

export type Workspace = {
  id: string;
  name: string;
  kind: OrgKind;
  // A sandbox stops working at this time. Null never expires.
  expires_at: string | null;
  // What an empty workspace still needs, for the onboarding checklist.
  checklist: {
    guidelines: boolean;
    approved_rules: boolean;
    teammates: boolean;
    first_draft: boolean;
  };
};

// contracts/v4: the CI/CD integration (docs/ci-integration.md). A CI job submits the copy
// files it found as a run and reads back the server's verdict.
export type CIChannel =
  | "blog"
  | "linkedin"
  | "email"
  | "ad"
  | "banner"
  | "document";
export type CIRunState = "queued" | "running" | "done" | "error";
export type CIResult = "pass" | "fail";

export type CIPolicy = {
  severity_threshold: Severity;
  fail_on_unsure: boolean;
};

export type CIFinding = {
  id: string;
  rule_id: string | null;
  severity: Severity;
  verdict: Verdict;
  status: FindingStatus;
  // A short quote of the flagged text.
  span: string;
  // 1-based line in the submitted text, when known.
  line: number | null;
  title: string;
  url: string;
  // True when this finding is why the run fails.
  blocking: boolean;
};

export type CIFileResult = {
  path: string;
  content_id: string;
  review_id: string;
  state: CIRunState;
  findings: CIFinding[];
};

export type CIRunStatus = {
  id: string;
  state: CIRunState;
  // Set once the run is done. An error run has no result, and never counts as a pass.
  result: CIResult | null;
  reasons: string[];
  files: CIFileResult[];
  url: string;
  policy: CIPolicy;
};
