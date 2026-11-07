"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import {
  ErrorNotice,
  ScreenHeader,
  SELECT_STYLE,
  useLoaded,
} from "@/components/brand-ui";
import { Label } from "@/components/ui/label";
import { getFacts } from "@/lib/admin";
import { type Graph, type GraphNode, getGraph } from "@/lib/graph";

const COLUMN_ORDER = ["fact", "claim", "content"];
const WIDTH = 760;
const ROW = 56;
const NODE_W = 200;
const NODE_H = 36;

function columnOf(node: GraphNode): number {
  const index = COLUMN_ORDER.indexOf(node.type.toLowerCase());
  return index === -1 ? COLUMN_ORDER.length : index;
}

function shorten(text: string, limit = 28): string {
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

/** A fixed left-to-right layout: facts, then the claims citing them, then content. */
function layout(graph: Graph) {
  const columns = new Map<number, GraphNode[]>();
  for (const node of graph.nodes) {
    const column = columnOf(node);
    columns.set(column, [...(columns.get(column) ?? []), node]);
  }
  const count = Math.max(...columns.keys(), 0) + 1;
  const tallest = Math.max(1, ...[...columns.values()].map((c) => c.length));
  const height = tallest * ROW + 16;
  const step = count > 1 ? (WIDTH - NODE_W) / (count - 1) : 0;
  const place = new Map<string, { x: number; y: number }>();
  for (const [column, nodes] of columns) {
    const top = (height - nodes.length * ROW) / 2;
    nodes.forEach((node, row) => {
      place.set(node.id, { x: column * step, y: top + row * ROW + 10 });
    });
  }
  return { place, height };
}

function GraphPicture({ graph }: { graph: Graph }) {
  const { place, height } = layout(graph);
  const label = new Map(graph.nodes.map((node) => [node.id, node.label]));
  return (
    <div className="mt-4 overflow-x-auto rounded-lg border p-3">
      <svg
        role="img"
        aria-label={`${graph.nodes.length} nodes and ${graph.edges.length} links. The same links are listed below.`}
        viewBox={`0 0 ${WIDTH} ${height}`}
        className="min-w-[640px]"
      >
        {graph.edges.map((edge) => {
          const from = place.get(edge.source);
          const to = place.get(edge.target);
          if (!from || !to) return null;
          const [left, right] = from.x <= to.x ? [from, to] : [to, from];
          return (
            <line
              key={`${edge.source}-${edge.target}-${edge.type}`}
              x1={left.x + NODE_W}
              y1={left.y + NODE_H / 2}
              x2={right.x}
              y2={right.y + NODE_H / 2}
              className="stroke-muted-foreground"
              strokeWidth={1.5}
            />
          );
        })}
        {graph.nodes.map((node) => {
          const at = place.get(node.id)!;
          return (
            <g key={node.id} transform={`translate(${at.x} ${at.y})`}>
              <title>{`${node.type}: ${label.get(node.id)}`}</title>
              <rect
                width={NODE_W}
                height={NODE_H}
                rx={6}
                className={
                  node.type.toLowerCase() === "fact"
                    ? "fill-primary"
                    : "fill-background stroke-border"
                }
                strokeWidth={1}
              />
              <text
                x={10}
                y={NODE_H / 2 + 4}
                className={`text-[12px] ${node.type.toLowerCase() === "fact" ? "fill-primary-foreground" : "fill-foreground"}`}
              >
                {shorten(node.label)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function GraphScreen() {
  const facts = useLoaded(getFacts);
  const [root, setRoot] = useState("");
  const chosen = root || facts.data?.[0]?.id || "";
  const load = useCallback(
    () =>
      chosen
        ? getGraph(chosen)
        : Promise.resolve<Graph>({ nodes: [], edges: [] }),
    [chosen],
  );
  const { data: graph, error } = useLoaded(load);
  const names = new Map(graph?.nodes.map((node) => [node.id, node]) ?? []);

  return (
    <div className="mx-auto w-full max-w-5xl">
      <ScreenHeader
        title="Memory graph"
        summary="Which claims cite a fact, and which pieces hold those claims."
      />
      <div className="mt-4 flex flex-col gap-1">
        <Label htmlFor="graph-root">Fact</Label>
        <select
          id="graph-root"
          className={`${SELECT_STYLE} w-80`}
          value={chosen}
          onChange={(event) => setRoot(event.target.value)}
        >
          {(facts.data ?? []).map((fact) => (
            <option key={fact.id} value={fact.id}>
              {fact.id}: {shorten(fact.statement, 50)}
            </option>
          ))}
        </select>
      </div>

      <ErrorNotice message={error ?? facts.error} />
      {graph && graph.edges.length === 0 && (
        <p className="mt-6 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No reviewed claim cites this fact yet.
        </p>
      )}
      {graph && graph.edges.length > 0 && (
        <>
          <GraphPicture graph={graph} />
          <h2 className="mt-6 font-semibold">Links</h2>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {graph.edges.map((edge) => {
              const source = names.get(edge.source);
              const target = names.get(edge.target);
              const show = (node?: GraphNode, id?: string) =>
                node?.type.toLowerCase() === "content" ? (
                  <Link className="underline" href={`/content/${node.id}`}>
                    {node.label}
                  </Link>
                ) : (
                  <span>{node?.label ?? id}</span>
                );
              return (
                <li key={`${edge.source}-${edge.target}-${edge.type}`}>
                  {show(source, edge.source)}{" "}
                  <span className="text-muted-foreground">
                    {edge.type.toLowerCase()}
                  </span>{" "}
                  {show(target, edge.target)}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
