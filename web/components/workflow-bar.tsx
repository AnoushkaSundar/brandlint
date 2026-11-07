"use client";

import { useState } from "react";

import { ReasonForm } from "@/components/reason-form";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { STATE_LABELS } from "@/lib/content";
import type { ContentState } from "@/lib/contracts";
import type { Board, MoveOption } from "@/lib/workflow";

const MOVE_LABELS: Partial<Record<ContentState, string>> = {
  reviewer_check: "Submit for review",
  resolving: "Request changes",
  manager_approval: "Send to manager",
  legal_signoff: "Send to legal",
  published: "Publish",
  rejected: "Reject",
};

function Move({
  move,
  onMove,
}: {
  move: MoveOption;
  onMove: (to: ContentState, reason?: string) => Promise<void>;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const label = MOVE_LABELS[move.to] ?? STATE_LABELS[move.to];

  if (asking) {
    return (
      <ReasonForm
        label={`Why: ${label.toLowerCase()}?`}
        submitLabel={label}
        onSubmit={(reason) => onMove(move.to, reason)}
        onCancel={() => setAsking(false)}
      />
    );
  }

  function start() {
    if (move.needs_reason) {
      setAsking(true);
      return;
    }
    setBusy(true);
    setError(null);
    onMove(move.to)
      .catch((caught: ApiError) => setError(caught.message))
      .finally(() => setBusy(false));
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        size="sm"
        variant={move.to === "rejected" ? "outline" : "default"}
        disabled={busy || move.blocked_by !== null}
        onClick={start}
      >
        {label}
      </Button>
      {move.blocked_by && <p>{move.blocked_by}</p>}
      {error && (
        <p role="alert" className="border-l-2 border-destructive pl-2">
          {error}
        </p>
      )}
    </div>
  );
}

function Restart({ onRestart }: { onRestart: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function restart() {
    setBusy(true);
    setError(null);
    onRestart().catch((caught: ApiError) => {
      setError(caught.message);
      setBusy(false);
    });
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button type="button" size="sm" disabled={busy} onClick={restart}>
        Start review again
      </Button>
      {error && (
        <p role="alert" className="border-l-2 border-destructive pl-2">
          {error}
        </p>
      )}
    </div>
  );
}

export function WorkflowBar({
  board,
  onMove,
  onRestart,
}: {
  board: Board;
  onMove: (to: ContentState, reason?: string) => Promise<void>;
  onRestart: () => Promise<void>;
}) {
  // Leaving AI review happens by itself when the run ends, so it's never a button.
  const inAiReview = board.state === "ai_review";
  const moves = board.moves.filter(
    (move) => !inAiReview || move.to !== "resolving",
  );
  const waiting = inAiReview
    ? board.moves.find((move) => move.to === "resolving")?.blocked_by
    : null;

  return (
    <section
      aria-label="Workflow"
      className="mt-4 flex flex-col gap-2 rounded-lg border p-3 text-sm"
    >
      <p>
        Status: <span className="font-medium">{STATE_LABELS[board.state]}</span>
      </p>
      {waiting && <p>{waiting}</p>}
      {board.can_restart && <Restart onRestart={onRestart} />}
      {board.hidden_overridden && (
        <p className="border-l-2 border-destructive pl-2">
          A reviewer let hidden text through. It&apos;s still in the content,
          so check it before approving.
        </p>
      )}
      {board.legal_required && (
        <p>A high-severity claim means legal must sign this off.</p>
      )}
      {moves.map((move) => (
        <Move key={move.to} move={move} onMove={onMove} />
      ))}
    </section>
  );
}
