import { apiFetch } from "@/lib/api";
import type { ContentSummary } from "@/lib/content";
import type {
  CheckType,
  ContentState,
  DecisionAction,
  Severity,
  Span,
} from "@/lib/contracts";

export type QueueItem = {
  content_id: string;
  title: string;
  channel: string;
  state: ContentState;
  finding_id: string;
  kind: "unsure" | "override" | "fix";
  severity: Severity;
  check: CheckType;
  explanation: string;
  reason: string | null;
  fix_text: string | null;
};

export type Queue = {
  items: QueueItem[];
  ready: ContentSummary[];
};

export type Comment = {
  id: string;
  content_version_id: string;
  finding_id: string | null;
  span: Span | null;
  parent_id: string | null;
  author: string;
  body: string;
  mentions: string[];
  created_at: string;
};

export type CommentInput = {
  body: string;
  content_version_id: string;
  finding_id?: string | null;
  parent_id?: string | null;
};

export type StateEntry = {
  from_state: ContentState;
  to_state: ContentState;
  actor: string;
  reason: string | null;
  created_at: string;
};

export type DecisionEntry = {
  finding_id: string;
  action: DecisionAction;
  actor: string;
  role: string;
  reason: string | null;
  version: number;
  created_at: string;
};

export type PublishedStamp = {
  version: number;
  rulebook_version: number;
  approvers: string[];
  published_at: string;
};

export type History = {
  states: StateEntry[];
  decisions: DecisionEntry[];
  stamp: PublishedStamp | null;
};

export type AuditEntry = {
  id: string;
  actor: string;
  role: string;
  action: string;
  target_type: string;
  target_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  rulebook_version: number | null;
  created_at: string;
};

export type AuditPage = {
  total: number;
  items: AuditEntry[];
};

export type AuditFilters = {
  action?: string;
  role?: string;
  limit: number;
  offset: number;
};

export const ACTION_LABELS: Record<DecisionAction, string> = {
  accept_fix: "Accepted a fix",
  edit_fix: "Edited a fix",
  override: "Overrode",
  confirm_override: "Confirmed an override",
  reject_override: "Rejected an override",
  resolve: "Resolved",
};

export function getQueue(): Promise<Queue> {
  return apiFetch<Queue>("/workflow/queue");
}

export function getComments(contentId: string): Promise<Comment[]> {
  return apiFetch<Comment[]>(`/workflow/content/${contentId}/comments`);
}

export function postComment(
  contentId: string,
  input: CommentInput,
): Promise<Comment[]> {
  return apiFetch<Comment[]>(`/workflow/content/${contentId}/comments`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getHistory(contentId: string): Promise<History> {
  return apiFetch<History>(`/workflow/content/${contentId}/history`);
}

export function getAudit(filters: AuditFilters): Promise<AuditPage> {
  const params = new URLSearchParams({
    limit: String(filters.limit),
    offset: String(filters.offset),
  });
  if (filters.action) params.set("action", filters.action);
  if (filters.role) params.set("role", filters.role);
  return apiFetch<AuditPage>(`/workflow/audit?${params}`);
}

export function formatTime(value: string): string {
  return new Date(value).toLocaleString("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
