import { apiFetch } from "@/lib/api";

export type RuleOverrides = {
  findings: number;
  overridden: number;
  rate: number;
  may_be_unclear: boolean;
};

export type Signals = {
  pieces: number;
  reviewed: number;
  top_rules: { rule_id: string; findings: number }[];
  override_rate_by_rule: Record<string, RuleOverrides>;
  vote_split_by_rule: Record<
    string,
    { voted: number; split: number; rate: number }
  >;
  findings_by_day: { day: string; findings: number }[];
  findings_by_check: Record<string, number>;
  creator_signals: {
    creator: string;
    overrides: number;
    rejected_rate: number;
  }[];
  gaps: {
    id: string;
    review_id: string;
    check: string;
    text: string;
    explanation: string;
    created_at: string;
  }[];
  unavailable: string[];
};

export type SpotCheck = { content_id: string; review_id: string };

export function getSignals(filters: {
  channel?: string;
  source?: string;
}): Promise<Signals> {
  const query = new URLSearchParams();
  if (filters.channel) query.set("channel", filters.channel);
  if (filters.source) query.set("source", filters.source);
  const suffix = query.size ? `?${query}` : "";
  return apiFetch<Signals>(`/insights/signals${suffix}`);
}

export function getSpotChecks(): Promise<SpotCheck[]> {
  return apiFetch<SpotCheck[]>("/governance/spot-checks");
}

export function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}
