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

function shorten(text: string, limit = 28): string {
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

const VERBS: Record<string, string> = {
  supported_by: "is supported by",
  cites: "cites",
  contains: "contains",
};

type ClaimRow = { text: string; pieces: GraphNode[] };

/** The fact's source, the claims citing it, and the pieces holding each claim.
 * Claims with the same wording are merged, so each one appears once. */
function relations(graph: Graph, factId: string) {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const kind = (edge: { type: string }) => edge.type.toLowerCase();
  const sources = graph.edges
    .filter((edge) => kind(edge) === "supported_by" && edge.source === factId)
    .map((edge) => byId.get(edge.target)?.label ?? edge.target);
  const rows = new Map<string, Map<string, GraphNode>>();
  for (const edge of graph.edges) {
    if (kind(edge) !== "cites" || edge.target !== factId) continue;
    const claim = byId.get(edge.source);
    if (!claim) continue;
    const pieces = rows.get(claim.label) ?? new Map<string, GraphNode>();
    for (const holds of graph.edges) {
      const piece = byId.get(holds.source);
      if (kind(holds) === "contains" && holds.target === claim.id && piece) {
        pieces.set(piece.id, piece);
      }
    }
    rows.set(claim.label, pieces);
  }
  const claims: ClaimRow[] = [...rows].map(([text, pieces]) => ({
    text,
    pieces: [...pieces.values()],
  }));
  return { sources, claims };
}

function Arrow() {
  return (
    <span aria-hidden="true" className="hidden self-center text-muted-foreground md:block">
      &rarr;
    </span>
  );
}

function Relations({
  graph,
  factId,
  statement,
}: {
  graph: Graph;
  factId: string;
  statement?: string;
}) {
  const { sources, claims } = relations(graph, factId);
  const pieceCount = new Set(claims.flatMap((row) => row.pieces.map((p) => p.id))).size;
  return (
    <>
      <p className="mt-6 text-sm">
        <strong>{factId}</strong> is cited by {claims.length}{" "}
        {claims.length === 1 ? "claim" : "claims"} in {pieceCount}{" "}
        {pieceCount === 1 ? "piece" : "pieces"}. If the fact changes, those pieces
        are queued for a re-review.
      </p>
      <div className="mt-4 grid gap-4 rounded-xl border p-4 md:grid-cols-[minmax(0,16rem)_auto_minmax(0,1fr)]">
        <section aria-labelledby="graph-fact">
          <h3 id="graph-fact" className="text-xs font-medium text-muted-foreground uppercase">
            Approved fact
          </h3>
          <div className="mt-2 rounded-lg bg-primary p-3 text-primary-foreground">
            <p className="font-semibold">{factId}</p>
            {statement && <p className="mt-1 text-sm">{statement}</p>}
          </div>
          {sources.length > 0 && (
            <p className="mt-2 text-sm text-muted-foreground">
              Source: {sources.join(", ")}
            </p>
          )}
        </section>
        <Arrow />
        <section aria-labelledby="graph-claims">
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,14rem)]">
            <h3 id="graph-claims" className="text-xs font-medium text-muted-foreground uppercase">
              Claims that cite it
            </h3>
            <span className="hidden md:block" />
            <h3 className="hidden text-xs font-medium text-muted-foreground uppercase md:block">
              Pieces that contain the claim
            </h3>
          </div>
          <ul className="mt-2 flex flex-col gap-3">
            {claims.map((row) => (
              <li
                key={row.text}
                className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,14rem)]"
              >
                <p className="rounded-lg border p-3 text-sm">&ldquo;{row.text}&rdquo;</p>
                <Arrow />
                <ul className="flex flex-col gap-2" aria-label="Pieces that contain the claim">
                  <li aria-hidden="true" className="text-xs font-medium text-muted-foreground uppercase md:hidden">
                    Contained in
                  </li>
                  {row.pieces.map((piece) => (
                    <li key={piece.id}>
                      <Link
                        href={`/content/${piece.id}`}
                        className="block rounded-lg border p-3 text-sm font-medium underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                      >
                        {piece.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
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
          <Relations
            graph={graph}
            factId={chosen}
            statement={facts.data?.find((fact) => fact.id === chosen)?.statement}
          />
          <details className="mt-6">
            <summary className="cursor-pointer font-semibold">All links</summary>
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
                    {VERBS[edge.type.toLowerCase()] ?? edge.type.toLowerCase()}
                  </span>{" "}
                  {show(target, edge.target)}
                </li>
              );
            })}
          </ul>
          </details>
        </>
      )}
    </div>
  );
}
