import { apiFetch } from "@/lib/api";
import type {
  Asset,
  AssetKind,
  DataClass,
  Fact,
  Rule,
  Severity,
  Term,
} from "@/lib/contracts";

export function getRulebook(version?: number): Promise<Rule[]> {
  const query = version === undefined ? "" : `?version=${version}`;
  return apiFetch<Rule[]>(`/admin/rulebook${query}`);
}

export type IngestJob = {
  id: string;
  status: "pending" | "done" | "failed";
  error: string | null;
  result: { version: number; rules: string[]; conflicts: string[][] } | null;
};

export type Drafts = {
  version: number;
  drafts: Rule[];
  conflicts: string[][];
};

export type DraftEdit = {
  text: string;
  severity: Severity;
  channel_scope: string[];
  required_text: string | null;
};

export function ingestGuideline(file: File): Promise<IngestJob> {
  const body = new FormData();
  body.append("file", file);
  return apiFetch<IngestJob>("/admin/ingest", { method: "POST", body });
}

export function getDrafts(): Promise<Drafts> {
  return apiFetch<Drafts>("/admin/rules/drafts");
}

export function editDraft(id: string, edit: DraftEdit): Promise<Rule> {
  return apiFetch<Rule>(`/admin/rules/${encodeURIComponent(id)}/draft`, {
    method: "PUT",
    body: JSON.stringify(edit),
  });
}

export function rejectDraft(id: string): Promise<void> {
  return apiFetch<void>(`/admin/rules/${encodeURIComponent(id)}/draft`, {
    method: "DELETE",
  });
}

export function approveRules(ruleIds: string[]): Promise<{ version: number }> {
  return apiFetch("/admin/rules/approve", {
    method: "POST",
    body: JSON.stringify({ rule_ids: ruleIds }),
  });
}

export type FactInput = {
  statement: string;
  value: string;
  source_doc: string;
  owner: string;
  valid_until: string | null;
  data_class: DataClass;
};

export type Impact = { content_id: string; state: string; claim_text: string };

export function getFacts(): Promise<Fact[]> {
  return apiFetch<Fact[]>("/admin/facts");
}

export function createFact(fact: FactInput): Promise<Fact> {
  return apiFetch<Fact>("/admin/facts", {
    method: "POST",
    body: JSON.stringify(fact),
  });
}

export function updateFact(
  id: string,
  fact: FactInput,
): Promise<{ fact: Fact; impact: Impact[] }> {
  return apiFetch(`/admin/facts/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(fact),
  });
}

export type TermInput = {
  preferred: string;
  banned: string[];
  renamed_from: string | null;
  rule_id: string | null;
};

export function getTerms(): Promise<Term[]> {
  return apiFetch<Term[]>("/admin/terms");
}

export function saveTerm(term: TermInput, id?: string): Promise<Term> {
  return apiFetch<Term>(
    id ? `/admin/terms/${encodeURIComponent(id)}` : "/admin/terms",
    { method: id ? "PUT" : "POST", body: JSON.stringify(term) },
  );
}

export function getAssets(): Promise<Asset[]> {
  return apiFetch<Asset[]>("/admin/assets");
}

export function addPalette(colours: string[]): Promise<Asset> {
  return apiFetch<Asset>("/admin/assets/palette", {
    method: "POST",
    body: JSON.stringify({ colours }),
  });
}

export function uploadAsset(kind: AssetKind, file: File): Promise<Asset> {
  const body = new FormData();
  body.append("kind", kind);
  body.append("file", file);
  return apiFetch<Asset>("/admin/assets", { method: "POST", body });
}

const DAY_MS = 24 * 60 * 60 * 1000;
export const EXPIRY_WARNING_DAYS = 30;

/** Whether a fact has expired or soon will, from its valid_until date. */
export function expiry(
  validUntil: string | null | undefined,
  today: Date = new Date(),
): "expired" | "soon" | null {
  if (!validUntil) return null;
  const end = new Date(`${validUntil}T23:59:59`);
  const left = end.getTime() - today.getTime();
  if (left < 0) return "expired";
  return left <= EXPIRY_WARNING_DAYS * DAY_MS ? "soon" : null;
}

export function getImpact(factId: string): Promise<Impact[]> {
  return apiFetch<Impact[]>(
    `/memory/impact?fact_id=${encodeURIComponent(factId)}`,
  );
}

export function queueRereview(
  factId: string,
  contentIds: string[],
): Promise<{ queued: string[] }> {
  return apiFetch(`/admin/facts/${encodeURIComponent(factId)}/rereview`, {
    method: "POST",
    body: JSON.stringify({ content_ids: contentIds }),
  });
}
