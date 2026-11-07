import { apiFetch } from "@/lib/api";
import type { Proposal } from "@/lib/contracts";

export function getProposals(): Promise<Proposal[]> {
  return apiFetch<Proposal[]>("/governance/proposals");
}

/** Runs the governance agent. It only drafts proposals; it never changes a rule. */
export function runGovernance(): Promise<Proposal[]> {
  return apiFetch<Proposal[]>("/governance/run", { method: "POST" });
}

export function decideProposal(
  id: string,
  status: "approved" | "rejected",
): Promise<Proposal[]> {
  return apiFetch<Proposal[]>(
    `/governance/proposals/${encodeURIComponent(id)}`,
    { method: "POST", body: JSON.stringify({ status }) },
  );
}

export type Disclosure = {
  models: string[];
  masked: Record<string, number>;
  routes: string[];
};

export type MaskingPreview = { original: string; sent: string };

export function getDisclosure(reviewId: string): Promise<Disclosure> {
  return apiFetch<Disclosure>(
    `/gateway/reviews/${encodeURIComponent(reviewId)}/disclosure`,
  );
}

export function getMaskingPreview(reviewId: string): Promise<MaskingPreview> {
  return apiFetch<MaskingPreview>(
    `/gateway/reviews/${encodeURIComponent(reviewId)}/masking-preview`,
  );
}
