import { apiFetch } from "@/lib/api";
import type { ContentState, DataClass } from "@/lib/contracts";

export type ContentSummary = {
  id: string;
  title: string;
  channel: string;
  source: string;
  data_class: DataClass;
  state: ContentState;
  creator_id: string;
  created_at: string;
};

export type ContentVersion = {
  id: string;
  content_id: string;
  version: number;
  text: string;
  file_name: string | null;
  fixes_applied?: boolean;
  created_by: string;
  created_at: string;
};

export type Review = {
  id: string;
  content_version_id: string;
  engine_review_id: string;
  channel: string;
  rulebook_version: number;
  created_at: string;
};

export type ContentDetail = ContentSummary & {
  versions: ContentVersion[];
  latest_review: Review | null;
  // An admin asked for another review because a fact this piece cites changed.
  rereview?: { fact_id: string; requested_at: string } | null;
};

export const CHANNELS = [
  { value: "blog", label: "Blog" },
  { value: "linkedin", label: "LinkedIn" },
  { value: "email", label: "Email" },
  { value: "ad", label: "Ad" },
  { value: "banner", label: "Banner" },
  { value: "document", label: "Document" },
];

export const DATA_CLASSES = [
  { value: "public", label: "Public" },
  { value: "internal", label: "Internal" },
  { value: "confidential", label: "Confidential" },
  { value: "restricted", label: "Restricted" },
];

export const STATE_LABELS: Record<ContentState, string> = {
  draft: "Draft",
  ai_review: "AI review",
  resolving: "Resolving",
  reviewer_check: "Reviewer check",
  manager_approval: "Manager approval",
  legal_signoff: "Legal sign-off",
  published: "Published",
  rejected: "Rejected",
};

// Once a piece has been submitted, new text would skip the review it's in.
export const LOCKED_STATES: ContentState[] = [
  "reviewer_check",
  "manager_approval",
  "legal_signoff",
  "published",
  "rejected",
];

export const REVIEWABLE_STATES: ContentState[] = [
  "draft",
  "ai_review",
  "resolving",
];

export const ACCEPTED_FILES = ".txt,.md,.html,.htm,.docx,.pdf,.png,.jpg,.jpeg";

export function channelLabel(value: string): string {
  return CHANNELS.find((channel) => channel.value === value)?.label ?? value;
}

// "ci" is copy that a CI job sent. It is hidden from every other list.
export function listContent(source?: "ci"): Promise<ContentSummary[]> {
  return apiFetch<ContentSummary[]>(source ? `/content?source=${source}` : "/content");
}

export function getContent(id: string): Promise<ContentDetail> {
  return apiFetch<ContentDetail>(`/content/${id}`);
}

export function createContent(form: FormData): Promise<ContentDetail> {
  return apiFetch<ContentDetail>("/content", { method: "POST", body: form });
}

export function addVersion(id: string, form: FormData): Promise<ContentDetail> {
  return apiFetch<ContentDetail>(`/content/${id}/versions`, {
    method: "POST",
    body: form,
  });
}

export function startReview(id: string): Promise<Review> {
  return apiFetch<Review>(`/content/${id}/reviews`, { method: "POST" });
}

export function versionFilePath(versionId: string): string {
  return `/content/versions/${versionId}/file`;
}
