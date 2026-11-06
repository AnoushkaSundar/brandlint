import type { CheckType, Finding, Severity } from "@/lib/contracts";

export const SEVERITY_LABELS: Record<Severity, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export const CHECK_LABELS: Record<CheckType, string> = {
  tone: "Tone",
  terminology: "Terminology",
  messaging: "Messaging",
  claim: "Claim",
  visual: "Visual",
  accessibility: "Accessibility",
  hidden_content: "Hidden content",
  required_element: "Required element",
  tone_drift: "Tone drift",
};

/** An UNSURE finding can carry no confidence at all, which isn't the same as 0%. */
export function confidenceLabel(finding: Finding): string | null {
  if (finding.confidence <= 0) return null;
  return `${Math.round(finding.confidence * 100)}% confidence`;
}

/** Built-in security rules cite no clause, so they're named rather than numbered. */
export function sourceLabel(
  finding: Finding,
  clauseRefs: ReadonlyMap<string, string>,
): string {
  const parts: string[] = [];
  if (finding.rule_id?.startsWith("SEC-")) {
    parts.push("BrandLint security rule");
  } else if (finding.rule_id) {
    const clause = clauseRefs.get(finding.rule_id);
    const version = finding.rule_version
      ? `, version ${finding.rule_version}`
      : "";
    parts.push(
      `${finding.rule_id}${clause ? ` ${clause}` : ""}${version}`,
    );
  }
  return [...parts, ...finding.fact_ids].join(" · ");
}

export function modelLabel(finding: Finding): string {
  const models = finding.models_used.length
    ? finding.models_used
    : [finding.trace.model].filter(Boolean);
  return models.join(", ");
}

export type TrackProgress = {
  label: string;
  count: number;
  done: boolean;
};

function trackOf(finding: Finding): number {
  if (finding.tier === 0) return 0;
  if (finding.unit_type === "claim") return 2;
  return finding.unit_type === "document" ? 3 : 1;
}

/**
 * The stream has no progress event, so this reads progress from what has arrived.
 * Code checks always stream first, so an AI finding means they've finished.
 */
export function trackProgress(
  findings: readonly Finding[],
  finished: boolean,
): TrackProgress[] {
  const counts = [0, 0, 0, 0];
  for (const finding of findings) counts[trackOf(finding)] += 1;
  const aiStarted = findings.some((finding) => finding.tier > 0);

  return ["Code checks", "Chunk checks", "Claims", "Document"].map(
    (label, index) => ({
      label,
      count: counts[index],
      done: finished || (index === 0 && aiStarted),
    }),
  );
}
