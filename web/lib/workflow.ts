import { apiFetch } from "@/lib/api";
import type {
  ContentState,
  DecisionAction,
  FindingStatus,
  FixSuggestion,
} from "@/lib/contracts";

export type FindingStanding = {
  id: string;
  status: FindingStatus;
  fix_text: string | null;
  allowed: DecisionAction[];
};

export type MoveOption = {
  to: ContentState;
  needs_reason: boolean;
  blocked_by: string | null;
};

export type Board = {
  state: ContentState;
  legal_required: boolean;
  findings: FindingStanding[];
  moves: MoveOption[];
};

export type DecisionInput = {
  action: DecisionAction;
  reason?: string;
  fix_text?: string;
  // For accept_fix: which offer was on screen, so nothing unseen gets saved.
  attempt?: number;
};

export function getBoard(contentId: string): Promise<Board> {
  return apiFetch<Board>(`/workflow/content/${contentId}/board`);
}

/** `again` spends an attempt. Without it, the stored suggestion comes back. */
export function offerFix(
  contentId: string,
  findingId: string,
  again: boolean,
): Promise<FixSuggestion> {
  const finding = encodeURIComponent(findingId);
  return apiFetch<FixSuggestion>(
    `/workflow/content/${contentId}/findings/${finding}/fix`,
    { method: "POST", body: JSON.stringify({ again }) },
  );
}

export function decide(
  contentId: string,
  findingId: string,
  input: DecisionInput,
): Promise<Board> {
  const finding = encodeURIComponent(findingId);
  return apiFetch<Board>(
    `/workflow/content/${contentId}/findings/${finding}/decisions`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function moveContent(
  contentId: string,
  to: ContentState,
  reason?: string,
): Promise<Board> {
  return apiFetch<Board>(`/workflow/content/${contentId}/transitions`, {
    method: "POST",
    body: JSON.stringify({ to, reason }),
  });
}
