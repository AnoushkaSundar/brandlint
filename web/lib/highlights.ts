import type { Finding, Severity } from "@/lib/contracts";

// Most serious first. Sorting and overlapping highlights both follow this order.
export const SEVERITY_ORDER: readonly Severity[] = [
  "critical",
  "high",
  "medium",
  "low",
];

export type Highlight = {
  findingId: string;
  severity: Severity;
  start: number;
  end: number;
};

export type Segment = {
  text: string;
  start: number;
  findingIds: string[];
  severity: Severity | null;
};

function severityRank(severity: Severity): number {
  return SEVERITY_ORDER.indexOf(severity);
}

/** Groups highlights by chunk. Empty spans have no text to mark, so they're left out. */
export function highlightsByChunk(
  findings: readonly Finding[],
): Map<string, Highlight[]> {
  const byChunk = new Map<string, Highlight[]>();
  for (const finding of findings) {
    for (const span of finding.spans) {
      if (span.end <= span.start) continue;
      const highlights = byChunk.get(span.chunk_id) ?? [];
      highlights.push({
        findingId: finding.id,
        severity: finding.severity,
        start: span.start,
        end: span.end,
      });
      byChunk.set(span.chunk_id, highlights);
    }
  }
  return byChunk;
}

/** Splits text at every highlight edge, so overlapping highlights stay separate. */
export function segmentText(
  text: string,
  highlights: readonly Highlight[],
): Segment[] {
  const edges = new Set([0, text.length]);
  for (const { start, end } of highlights) {
    edges.add(Math.min(start, text.length));
    edges.add(Math.min(end, text.length));
  }
  const sorted = [...edges].sort((a, b) => a - b);

  const segments: Segment[] = [];
  for (let index = 0; index < sorted.length - 1; index += 1) {
    const start = sorted[index];
    const end = sorted[index + 1];
    const covering = highlights.filter(
      (highlight) => highlight.start <= start && highlight.end >= end,
    );
    const worst = covering.reduce<Severity | null>(
      (current, { severity }) =>
        current === null || severityRank(severity) < severityRank(current)
          ? severity
          : current,
      null,
    );
    segments.push({
      text: text.slice(start, end),
      start,
      findingIds: covering.map((highlight) => highlight.findingId),
      severity: worst,
    });
  }
  return segments;
}

/** Sorts by severity, then by where the finding first appears in the document. */
export function sortFindings(
  findings: readonly Finding[],
  chunkOrder: ReadonlyMap<string, number>,
): Finding[] {
  const position = (finding: Finding): [number, number] => {
    const span = finding.spans[0];
    if (!span) return [Number.MAX_SAFE_INTEGER, 0];
    return [chunkOrder.get(span.chunk_id) ?? Number.MAX_SAFE_INTEGER, span.start];
  };

  return [...findings].sort((a, b) => {
    const bySeverity = severityRank(a.severity) - severityRank(b.severity);
    if (bySeverity !== 0) return bySeverity;
    const [chunkA, startA] = position(a);
    const [chunkB, startB] = position(b);
    return chunkA - chunkB || startA - startB;
  });
}
