"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { FindingCard } from "@/components/finding-card";
import type { FixDecision } from "@/components/fix-panel";
import { ReviewDocument } from "@/components/review-document";
import { getRulebook } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import {
  type ContentDetail,
  getContent,
  versionFilePath,
} from "@/lib/content";
import type { Chunk, Finding } from "@/lib/contracts";
import { getChunks, streamFindings } from "@/lib/engineClient";
import { trackProgress } from "@/lib/findingLabels";
import { sortFindings } from "@/lib/highlights";

type StreamState = "streaming" | "done" | "error";

function findingCount(count: number): string {
  return count === 1 ? "1 finding" : `${count} findings`;
}

function Findings({
  findings,
  streamState,
  selectedId,
  clauseRefs,
  decisions,
  onSelect,
  onDecide,
}: {
  findings: readonly Finding[];
  streamState: StreamState;
  selectedId: string | null;
  clauseRefs: ReadonlyMap<string, string>;
  decisions: ReadonlyMap<string, FixDecision>;
  onSelect: (findingId: string) => void;
  onDecide: (findingId: string, action: FixDecision, text: string) => void;
}) {
  return (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="findings-heading" className="text-lg font-semibold">
          Findings
        </h2>
        <p role="status" className="text-sm text-muted-foreground">
          {streamState === "done"
            ? `Finished: ${findingCount(findings.length)}`
            : `Checking… ${findingCount(findings.length)} so far`}
        </p>
      </div>

      <ul aria-label="Progress" className="mt-2 flex flex-wrap gap-x-4 text-sm">
        {trackProgress(findings, streamState === "done").map((track) => (
          <li key={track.label}>
            {track.label}: {track.count}
            <span className="text-muted-foreground">
              {track.done ? ", done" : ", checking"}
            </span>
          </li>
        ))}
      </ul>

      {streamState === "error" && (
        <p
          role="alert"
          className="mt-3 rounded-lg border border-destructive p-3 text-sm text-destructive"
        >
          The review stopped before it finished. Reload the page to try again.
        </p>
      )}

      {streamState === "done" && findings.length === 0 && (
        <p className="mt-3 rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          No issues found.
        </p>
      )}

      <ol className="mt-3 flex flex-col gap-2">
        {findings.map((finding) => (
          <li key={finding.id}>
            <FindingCard
              finding={finding}
              selected={finding.id === selectedId}
              clauseRefs={clauseRefs}
              decision={decisions.get(finding.id)}
              onSelect={onSelect}
              onDecide={onDecide}
            />
          </li>
        ))}
      </ol>
    </>
  );
}

export function ReviewScreen({ id }: { id: string }) {
  const [content, setContent] = useState<ContentDetail | null>(null);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [received, setReceived] = useState<Finding[]>([]);
  const [streamState, setStreamState] = useState<StreamState>("streaming");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [clauseRefs, setClauseRefs] = useState<ReadonlyMap<string, string>>(
    new Map(),
  );
  const [decisions, setDecisions] = useState<
    ReadonlyMap<string, FixDecision>
  >(new Map());
  const [error, setError] = useState<string | null>(null);
  const documentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let current = true;
    getContent(id).then(
      (loaded) => {
        if (current) setContent(loaded);
      },
      (caught: ApiError) => {
        if (current) setError(caught.message);
      },
    );
    return () => {
      current = false;
    };
  }, [id]);

  const reviewId = content?.latest_review?.engine_review_id;
  const rulebookVersion = content?.latest_review?.rulebook_version;

  useEffect(() => {
    if (!rulebookVersion) return;
    let current = true;
    // Clause numbers only add detail: every card still quotes its source without them.
    getRulebook(rulebookVersion).then(
      (rules) => {
        if (current) {
          setClauseRefs(new Map(rules.map((rule) => [rule.id, rule.clause_ref])));
        }
      },
      () => {},
    );
    return () => {
      current = false;
    };
  }, [rulebookVersion]);

  useEffect(() => {
    if (!reviewId) return;
    let current = true;

    getChunks(reviewId).then(
      (loaded) => {
        if (current) setChunks(loaded);
      },
      (caught: ApiError) => {
        if (current) setError(caught.message);
      },
    );

    const close = streamFindings(reviewId, {
      onFinding: (finding) =>
        setReceived((existing) =>
          existing.some((item) => item.id === finding.id)
            ? existing
            : [...existing, finding],
        ),
      onDone: () => setStreamState("done"),
      onError: () => setStreamState("error"),
    });

    return () => {
      current = false;
      close();
    };
  }, [reviewId]);

  const findings = useMemo(
    () =>
      sortFindings(
        received,
        new Map(chunks.map((chunk) => [chunk.id, chunk.ordinal])),
      ),
    [received, chunks],
  );

  function selectFinding(findingId: string) {
    setSelectedId(findingId);
    documentRef.current
      ?.querySelector(`mark[data-finding~="${CSS.escape(findingId)}"]`)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function decideFix(findingId: string, action: FixDecision) {
    setDecisions((existing) => new Map(existing).set(findingId, action));
  }

  const backLink = (
    <Link
      href={`/content/${id}`}
      className="text-sm text-muted-foreground underline underline-offset-2"
    >
      Back to details
    </Link>
  );

  if (!content) {
    return (
      <div className="mx-auto w-full max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Review</h1>
        {error ? (
          <p
            role="alert"
            className="mt-4 rounded-lg border border-destructive p-3 text-sm text-destructive"
          >
            {error}
          </p>
        ) : (
          <p role="status" className="mt-4 text-sm text-muted-foreground">
            Loading…
          </p>
        )}
      </div>
    );
  }

  const review = content.latest_review;

  if (!review) {
    return (
      <div className="mx-auto w-full max-w-3xl">
        {backLink}
        <h1 className="mt-3 text-2xl font-semibold tracking-tight">
          {content.title}
        </h1>
        <p className="mt-2 text-muted-foreground">
          This content hasn&apos;t been reviewed yet.
        </p>
      </div>
    );
  }

  const reviewed = content.versions.find(
    (version) => version.id === review.content_version_id,
  );

  return (
    <div className="mx-auto w-full max-w-6xl">
      {backLink}
      <h1 className="mt-3 text-2xl font-semibold tracking-tight">
        {content.title}
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Version {reviewed?.version} reviewed against rulebook version{" "}
        {review.rulebook_version}.
      </p>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-destructive p-3 text-sm text-destructive"
        >
          {error}
        </p>
      )}

      <div className="mt-5 grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section aria-label="Content being reviewed" ref={documentRef}>
          <ReviewDocument
            chunks={chunks}
            findings={findings}
            selectedId={selectedId}
            imagePath={
              reviewed?.file_name ? versionFilePath(reviewed.id) : null
            }
            imageAlt={`The uploaded image for ${content.title}`}
            onSelect={selectFinding}
          />
        </section>
        <section aria-labelledby="findings-heading">
          <Findings
            findings={findings}
            streamState={streamState}
            selectedId={selectedId}
            clauseRefs={clauseRefs}
            decisions={decisions}
            onSelect={selectFinding}
            onDecide={decideFix}
          />
        </section>
      </div>
    </div>
  );
}
