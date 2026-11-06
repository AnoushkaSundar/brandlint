import { apiFetch } from "@/lib/api";
import type { Rule } from "@/lib/contracts";

export function getRulebook(version: number): Promise<Rule[]> {
  return apiFetch<Rule[]>(`/admin/rulebook?version=${version}`);
}
