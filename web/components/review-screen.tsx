"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { CommentThread } from "@/components/comment-thread";
import { FindingCard } from "@/components/finding-card";
import { ReviewDocument } from "@/components/review-document";
import { SeverityBadge } from "@/components/severity-badge";
import { WorkflowBar } from "@/components/workflow-bar";
import { getRulebook } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import {
  type ContentDetail,
  getContent,
  startReview,
  versionFilePath,
} from "@/lib/content";
import type { Chunk, ContentState, Finding, Severity } from "@/lib/contracts";
import { getChunks, streamFindings } from "@/lib/engineClient";
import { trackProgress, UNSETTLED } from "@/lib/findingLabels";
import { sortFindings } from "@/lib/highlights";
import {
  type Comment,
  type CommentInput,
  getComments,
  postComment,
} from "@/lib/reviewDesk";
import {
  type Board,
  decide,
  type DecisionInput,
  type FindingStanding,
  getBoard,
  moveContent,
} from "@/lib/workflow";
import { cn } from "@/lib/utils";

type StreamState = "streaming" | "done" | "error";

const BOARD_POLL_MS = 2000;
const MAX_STREAM_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

function findingCount(count: number): string {
  return count === 1 ? "1 finding" : `${count} findings`;
}

const SEVERITIES: readonly Severity[] = ["critical", "high", "medium", "low"];
const GROUP_HINTS: Record<Severity, string> = {
  critical: "Only a reviewer can clear these.",
  high: "Only a reviewer can clear these.",
  medium: "Fix them, or override with a reason a reviewer confirms.",
  low: "Fix them, or override with a reason a reviewer confirms.",
};

/** What's left to do on this piece, at a glance. */
function Summary({
  findings,
  standings,
}: {
  findings: readonly Finding[];
  standings: ReadonlyMap<string, FindingStanding>;
}) {
  if (findings.length === 0) return null;
  const open = findings.filter((finding) =>
    UNSETTLED.includes(standings.get(finding.id)?.status ?? "open"),
  );
  const settled = findings.length - open.length;
  const unsure = open.filter((finding) => finding.verdict === "UNSURE").length;
  return (
    <div className="mt-3 rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex items-baseline justify-between gap-3">
        <p className="font-semibold">
          {open.length === 0
            ? "Every finding is settled"
            : `${findingCount(open.length)} to settle`}
        </p>
        <p className="text-sm text-muted-foreground">
          {settled} of {findings.length} settled
        </p>
      </div>
      <div
        className="mt-2 h-2 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label="Findings settled"
        aria-valuemin={0}
        aria-valuemax={findings.length}
        aria-valuenow={settled}
      >
        <div
          className="h-2 rounded-full bg-emerald-600 transition-all"
          style={{ width: `${(settled / findings.length) * 100}%` }}
        />
      </div>
      <ul className="mt-3 flex flex-wrap gap-2 text-sm">
        {SEVERITIES.map((severity) => {
          const count = open.filter((finding) => finding.severity === severity).length;
          return count > 0 ? (
            <li key={severity} className="flex items-center gap-1">
              <SeverityBadge severity={severity} />
              <span className="font-medium">{count}</span>
            </li>
          ) : null;
        })}
        {unsure > 0 && (
          <li className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-semibold text-violet-900">
            {unsure} the AI was unsure about
          </li>
        )}
      </ul>
    </div>
  );
}

function Findings({
  contentId,
  findings,
  streamState,
  selectedId,
  clauseRefs,
  standings,
  comments,
  versionId,
  onSelect,
  onDecide,
  onComment,
}: {
  contentId: string;
  findings: readonly Finding[];
  streamState: StreamState;
  selectedId: string | null;
  clauseRefs: ReadonlyMap<string, string>;
  standings: ReadonlyMap<string, FindingStanding>;
  comments: readonly Comment[];
  versionId: string;
  onSelect: (findingId: string) => void;
  onDecide: (findingId: string, input: DecisionInput) => Promise<void>;
  onComment: (input: CommentInput) => Promise<void>;
}) {
  return (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="findings-heading" className="text-lg font-semibold">
          Findings
        </h2>
        <p role="status" className="text-sm text-muted-foreground">
          {streamState === "done" && `Finished: ${findingCount(findings.length)}`}
          {streamState === "streaming" &&
            `Checking… ${findingCount(findings.length)} so far`}
          {streamState === "error" &&
            `Stopped: ${findingCount(findings.length)} so far`}
        </p>
      </div>

      <ul aria-label="Progress" className="mt-2 flex flex-wrap gap-2 text-xs">
        {trackProgress(findings, streamState === "done").map((track) => (
          <li
            key={track.label}
            className={cn(
              "rounded-full px-2 py-0.5",
              track.done ? "bg-emerald-50 text-emerald-900" : "bg-muted text-muted-foreground",
            )}
          >
            {track.done ? "✓ " : ""}
            {track.label}: {track.count}
            <span className="sr-only">
              {track.done && ", done"}
              {!track.done &&
                (streamState === "error" ? ", stopped" : ", checking")}
            </span>
            {!track.done && (streamState === "error" ? " · stopped" : " · checking")}
          </li>
        ))}
      </ul>

      <Summary findings={findings} standings={standings} />

      {streamState === "error" && (
        <p
          role="alert"
          className="mt-3 rounded-lg border border-destructive p-3 text-sm text-destructive"
        >
          The review stopped before it finished.
        </p>
      )}

      {streamState === "done" && findings.length === 0 && (
        <p className="mt-3 rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          No issues found.
        </p>
      )}

      {SEVERITIES.map((severity) => {
        const group = findings.filter((finding) => finding.severity === severity);
        if (group.length === 0) return null;
        return (
          <section key={severity} aria-label={`${severity} findings`} className="mt-5">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <h3 className="font-semibold capitalize">
                {severity} · {group.length}
              </h3>
              <p className="text-xs text-muted-foreground">{GROUP_HINTS[severity]}</p>
            </div>
            <ol className="mt-2 flex flex-col gap-3">
              {group.map((finding) => (
                <li key={finding.id}>
                  <FindingCard
                    contentId={contentId}
                    finding={finding}
                    selected={finding.id === selectedId}
                    clauseRefs={clauseRefs}
                    standing={standings.get(finding.id)}
                    comments={comments}
                    versionId={versionId}
                    onSelect={onSelect}
                    onDecide={onDecide}
                    onComment={onComment}
                  />
                </li>
              ))}
            </ol>
          </section>
        );
      })}
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
  const [board, setBoard] = useState<Board | null>(null);
  // Every board write takes a ticket, so a slow read can't undo a newer change.
  const boardTicket = useRef(0);
  const [comments, setComments] = useState<Comment[]>([]);
  const leftAiReview = useRef(false);
  const [streamAttempt, setStreamAttempt] = useState(0);
  const streamRetries = useRef(0);
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

  useEffect(() => {
    let current = true;
    getComments(id).then(
      (loaded) => {
        if (current) setComments(loaded);
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
      onDone: () => {
        // A good reconnect starts the count again and clears what went wrong before.
        streamRetries.current = 0;
        setError(null);
        setStreamState("done");
      },
      onError: () => setStreamState("error"),
    });

    return () => {
      current = false;
      close();
    };
  }, [reviewId, streamAttempt]);

  useEffect(() => {
    // The stream replays from the start, so reopening it fills in what was missed.
    // A board that couldn't load doesn't stop this: the outage may have hit both.
    const retry =
      streamState === "error" &&
      !board?.can_restart &&
      streamRetries.current < MAX_STREAM_RETRIES;
    if (!retry) return;
    streamRetries.current += 1;
    const timer = setTimeout(() => {
      setStreamState("streaming");
      setStreamAttempt((attempt) => attempt + 1);
    }, RETRY_DELAY_MS * streamRetries.current);
    return () => clearTimeout(timer);
  }, [streamState, board]);


  useEffect(() => {
    if (streamState === "streaming") return;
    let current = true;
    const ticket = boardTicket.current;
    getBoard(id).then(
      (loaded) => {
        if (current && ticket === boardTicket.current) setBoard(loaded);
      },
      (caught: ApiError) => {
        if (current) setError(caught.message);
      },
    );
    return () => {
      current = false;
    };
  }, [id, streamState]);

  useEffect(() => {
    const canLeave =
      board?.state === "ai_review" &&
      board.moves.some(
        (move) => move.to === "resolving" && move.blocked_by === null,
      );
    if (!canLeave || leftAiReview.current) return;
    leftAiReview.current = true;
    moveContent(id, "resolving").then(takeBoard, (caught: ApiError) => {
      leftAiReview.current = false;
      setError(caught.message);
    });
  }, [board, id]);

  useEffect(() => {
    // A dropped stream says nothing more, so keep asking until the run has ended.
    const waiting =
      board?.state === "ai_review" &&
      !board.can_restart &&
      board.moves.some(
        (move) => move.to === "resolving" && move.blocked_by !== null,
      );
    if (!waiting) return;
    const timer = setTimeout(() => {
      const ticket = boardTicket.current;
      getBoard(id).then(
        (loaded) => {
          if (ticket === boardTicket.current) setBoard(loaded);
        },
        () => {
          if (ticket === boardTicket.current) setBoard({ ...board });
        },
      );
    }, BOARD_POLL_MS);
    return () => clearTimeout(timer);
  }, [board, id]);

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

  const standings = useMemo(
    () => new Map(board?.findings.map((item) => [item.id, item])),
    [board],
  );

  const unsettled = useMemo(
    () =>
      findings.filter((finding) =>
        UNSETTLED.includes(standings.get(finding.id)?.status ?? "open"),
      ),
    [findings, standings],
  );

  function takeBoard(next: Board | null) {
    boardTicket.current += 1;
    setBoard(next);
  }

  async function decideFinding(findingId: string, input: DecisionInput) {
    takeBoard(await decide(id, findingId, input));
  }

  async function comment(input: CommentInput) {
    setComments(await postComment(id, input));
  }

  async function restart() {
    await startReview(id);
    // The new review id comes first, so the stream can't reopen the failed run.
    const fresh = await getContent(id);
    leftAiReview.current = false;
    streamRetries.current = 0;
    setError(null);
    setReceived([]);
    setChunks([]);
    takeBoard(null);
    setContent(fresh);
    setStreamState("streaming");
    setStreamAttempt((attempt) => attempt + 1);
  }

  async function move(to: ContentState, reason?: string) {
    takeBoard(await moveContent(id, to, reason));
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

      {board && (
        <WorkflowBar board={board} onMove={move} onRestart={restart} />
      )}

      <div className="mt-5 grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section aria-label="Content being reviewed" ref={documentRef}>
          <ReviewDocument
            chunks={chunks}
            findings={unsettled}
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
            contentId={id}
            findings={findings}
            streamState={streamState}
            selectedId={selectedId}
            clauseRefs={clauseRefs}
            standings={standings}
            comments={comments}
            versionId={review.content_version_id}
            onSelect={selectFinding}
            onDecide={decideFinding}
            onComment={comment}
          />
        </section>
      </div>

      <section aria-labelledby="comments-heading" className="mt-8 max-w-2xl">
        <h2 id="comments-heading" className="text-lg font-semibold">
          Comments on this version
        </h2>
        <div className="mt-3">
          <CommentThread
            label="Add a comment"
            comments={comments}
            versionId={review.content_version_id}
            onPost={comment}
          />
        </div>
      </section>
    </div>
  );
}
