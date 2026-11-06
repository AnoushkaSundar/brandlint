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
