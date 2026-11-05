"use client";

import { cn } from "@/lib/utils";

import { apiUrl } from "@/lib/api";
import type { Finding, Severity } from "@/lib/contracts";
import type { Chunk } from "@/lib/engineClient";
import { highlightsByChunk, type Segment, segmentText } from "@/lib/highlights";

// Colour plus an underline style, so severity doesn't rely on colour alone.
export const SEVERITY_MARK: Record<Severity, string> = {
  low: "bg-sky-100 decoration-sky-800 decoration-dotted",
  medium: "bg-amber-100 decoration-amber-800 decoration-dashed",
  high: "bg-orange-200 decoration-orange-900 decoration-solid",
  critical: "bg-red-200 font-medium decoration-red-900 decoration-double",
};

type DocumentProps = {
  chunks: readonly Chunk[];
  findings: readonly Finding[];
  selectedId: string | null;
  imagePath: string | null;
  imageAlt: string;
  onSelect: (findingId: string) => void;
};

function Highlighted({
  segment,
  selected,
  onSelect,
}: {
  segment: Segment;
  selected: boolean;
  onSelect: (findingId: string) => void;
}) {
  if (!segment.severity) return segment.text;

  return (
    <mark
      data-finding={segment.findingIds.join(" ")}
      data-selected={selected || undefined}
      className={cn(
        "rounded-sm text-foreground underline decoration-2 underline-offset-2",
        SEVERITY_MARK[segment.severity],
        selected && "outline-2 outline-offset-1 outline-ring",
      )}
    >
      <button
        type="button"
        onClick={() => onSelect(segment.findingIds[0])}
        className="inline cursor-pointer text-left underline decoration-inherit"
      >
        {segment.text}
        <span className="sr-only"> ({segment.severity} finding)</span>
      </button>
    </mark>
  );
}

export function ReviewDocument({
  chunks,
  findings,
  selectedId,
  imagePath,
  imageAlt,
  onSelect,
}: DocumentProps) {
  const highlights = highlightsByChunk(findings);

  return (
    <div className="flex flex-col gap-4 rounded-lg border p-5 leading-relaxed">
      {chunks.map((chunk) => {
        if (chunk.kind === "image") {
          return imagePath ? (
            // The file needs the session cookie, which next/image's optimiser lacks.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={chunk.id}
              src={apiUrl(imagePath)}
              alt={imageAlt}
              className="rounded-md border"
            />
          ) : null;
        }

        const body = segmentText(
          chunk.text,
          highlights.get(chunk.id) ?? [],
        ).map((segment) => (
          <Highlighted
            key={segment.start}
            segment={segment}
            selected={
              selectedId !== null && segment.findingIds.includes(selectedId)
            }
            onSelect={onSelect}
          />
        ));

        return chunk.kind === "heading" ? (
          <h2 key={chunk.id} className="text-xl font-semibold">
            {body}
          </h2>
        ) : (
          <p key={chunk.id}>{body}</p>
        );
      })}
    </div>
  );
}
