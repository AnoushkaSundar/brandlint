import { apiFetch } from "@/lib/api";
import type {
  ContentState,
  DecisionAction,
  FindingStatus,
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
};

export function getBoard(contentId: string): Promise<Board> {
  return apiFetch<Board>(`/workflow/content/${contentId}/board`);
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
