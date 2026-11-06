import { apiFetch, apiUrl } from "@/lib/api";
import type {
  DataClass,
  Finding,
  FixSuggestion,
  Precedent,
  Verdict,
} from "@/lib/contracts";

export type Chunk = {
  id: string;
  content_version_id: string;
  ordinal: number;
  kind: "heading" | "paragraph" | "image";
  text: string;
  content_hash: string;
  data_class: DataClass;
  style?: Record<string, unknown> | null;
};

export type ReplayResult = {
  identical: boolean;
  verdict: Verdict;
  manifest?: Record<string, unknown> | null;
};

type StreamHandlers = {
  onFinding: (finding: Finding) => void;
  onDone: () => void;
  onError: () => void;
};

export function getChunks(reviewId: string): Promise<Chunk[]> {
  return apiFetch<Chunk[]>(`/engine/reviews/${reviewId}/chunks`);
}

export function requestFix(findingId: string): Promise<FixSuggestion> {
  return apiFetch<FixSuggestion>(`/engine/findings/${findingId}/fix`, {
    method: "POST",
  });
}

export function replayVerdict(findingId: string): Promise<ReplayResult> {
  return apiFetch<ReplayResult>(`/engine/verdicts/${findingId}/replay`, {
    method: "POST",
  });
}

export function getPrecedents(findingId: string): Promise<Precedent[]> {
  return apiFetch<Precedent[]>(
    `/memory/precedents?finding_id=${encodeURIComponent(findingId)}`,
  );
}

/** Opens the findings stream and returns a function that closes it. */
export function streamFindings(
  reviewId: string,
  { onFinding, onDone, onError }: StreamHandlers,
): () => void {
  // withCredentials sends the session cookie, because EventSource can't set headers.
  const source = new EventSource(
    apiUrl(`/engine/reviews/${reviewId}/findings`),
    { withCredentials: true },
  );

  source.addEventListener("finding", (event) => {
    onFinding(JSON.parse(event.data));
  });
  source.addEventListener("done", () => {
    source.close();
    onDone();
  });
  // EventSource would otherwise reconnect and replay the whole stream.
  source.onerror = () => {
    source.close();
    onError();
  };

  return () => source.close();
}
