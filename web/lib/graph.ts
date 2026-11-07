import { apiFetch } from "@/lib/api";

export type GraphNode = { id: string; type: string; label: string };
export type GraphEdge = { source: string; target: string; type: string };
export type Graph = { nodes: GraphNode[]; edges: GraphEdge[] };

export function getGraph(root: string): Promise<Graph> {
  return apiFetch<Graph>(`/memory/graph?root=${encodeURIComponent(root)}`);
}
