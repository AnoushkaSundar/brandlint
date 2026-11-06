"use client";

import { useState } from "react";

import { TrackedChanges } from "@/components/tracked-changes";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import type { Finding, FixSuggestion } from "@/lib/contracts";
import { type DecisionInput, offerFix } from "@/lib/workflow";

const MAX_ATTEMPTS = 2;
const NO_SAFE_FIX = "No safe fix found; marked for review";

type FixState =
  | { kind: "closed" }
  | { kind: "loading"; message: string }
  | { kind: "showing"; fix: FixSuggestion; error?: string; exhausted?: boolean }
  | { kind: "editing"; fix: FixSuggestion; text: string }
  | { kind: "failed"; message: string; final: boolean };

export function FixPanel({
  contentId,
  finding,
  onDecide,
}: {
  contentId: string;
  finding: Finding;
  onDecide: (input: DecisionInput) => Promise<void>;
}) {
  const [state, setState] = useState<FixState>({ kind: "closed" });

  /** With a current fix this spends an attempt. Without one it reopens the stored offer. */
  function ask(current: FixSuggestion | null) {
    setState({ kind: "loading", message: "Writing a fix…" });
    offerFix(contentId, finding.id, current !== null).then(
      (fix) => setState({ kind: "showing", fix }),
      (caught: ApiError) => {
        const final = caught.status === 422;
        const message = final ? NO_SAFE_FIX : caught.message;
        setState(
          current
            ? { kind: "showing", fix: current, error: message, exhausted: final }
            : { kind: "failed", message, final },
        );
      },
    );
  }

  function save(input: DecisionInput, fix: FixSuggestion) {
    setState({ kind: "loading", message: "Saving…" });
    onDecide(input).catch((caught: ApiError) =>
      setState({ kind: "showing", fix, error: caught.message }),
    );
  }

  const close = () => setState({ kind: "closed" });

  if (state.kind === "closed") {
    return (
      <Button type="button" variant="outline" size="sm" onClick={() => ask(null)}>
        Suggest fix
      </Button>
    );
  }

  if (state.kind === "loading") {
    return (
      <p role="status" className="text-muted-foreground">
        {state.message}
      </p>
    );
  }

  if (state.kind === "failed") {
    return (
      <div className="flex w-full flex-col items-start gap-2">
        <p role="alert" className="border-l-2 border-destructive pl-2">
          {state.message}
        </p>
        <div className="flex flex-wrap gap-2">
          {!state.final && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => ask(null)}
            >
              Try again
            </Button>
          )}
          <Button type="button" variant="ghost" size="sm" onClick={close}>
            Close
          </Button>
        </div>
      </div>
    );
  }

  if (state.kind === "editing") {
    const fieldId = `fix-${finding.id}`;
    return (
      <div className="flex w-full flex-col gap-2">
        <Label htmlFor={fieldId}>Your version</Label>
        <Textarea
          id={fieldId}
          value={state.text}
          onChange={(event) =>
            setState({ ...state, text: event.target.value })
          }
        />
        <p className="text-muted-foreground">
          A reviewer will check your wording before this goes further.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            disabled={!state.text.trim()}
            onClick={() =>
              save(
                { action: "edit_fix", fix_text: state.text.trim() },
                state.fix,
              )
            }
          >
            Save edit
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setState({ kind: "showing", fix: state.fix })}
          >
            Back to suggestion
          </Button>
        </div>
      </div>
    );
  }

  const { fix, error, exhausted } = state;
  return (
    <div className="flex w-full flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-medium">
          Suggested fix, attempt {fix.attempt} of {MAX_ATTEMPTS}
        </p>
        <span className="rounded-sm border px-1.5 text-xs text-muted-foreground">
          AI suggestion
        </span>
      </div>
      <TrackedChanges before={fix.original} after={fix.suggested} />
      {error && (
        <p role="alert" className="border-l-2 border-destructive pl-2">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => save({ action: "accept_fix" }, fix)}
        >
          Accept
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            setState({ kind: "editing", fix, text: fix.suggested })
          }
        >
          Edit
        </Button>
        {fix.attempt < MAX_ATTEMPTS && !exhausted && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => ask(fix)}
          >
            Try another
          </Button>
        )}
        <Button type="button" variant="ghost" size="sm" onClick={close}>
          Close
        </Button>
      </div>
    </div>
  );
}
