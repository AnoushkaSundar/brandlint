"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import type { Finding, FixSuggestion } from "@/lib/contracts";
import { requestFix } from "@/lib/engineClient";
import { wordDiff } from "@/lib/wordDiff";

const MAX_ATTEMPTS = 2;
const NO_SAFE_FIX = "No safe fix found; marked for review";

export type FixDecision = "accept_fix" | "edit_fix";

type FixState =
  | { kind: "closed" }
  | { kind: "loading" }
  | { kind: "showing"; fix: FixSuggestion }
  | { kind: "editing"; fix: FixSuggestion; text: string }
  | { kind: "failed"; message: string; final: boolean };

function TrackedChanges({ fix }: { fix: FixSuggestion }) {
  return (
    <p className="rounded-md bg-muted p-2 leading-relaxed">
      {wordDiff(fix.original, fix.suggested).map((part, index) => {
        if (part.kind === "removed") {
          return (
            <del
              key={index}
              className="text-foreground line-through decoration-destructive decoration-2"
            >
              <span className="sr-only">Removed: </span>
              {part.text}
            </del>
          );
        }
        if (part.kind === "added") {
          return (
            <ins key={index} className="font-medium text-foreground underline">
              <span className="sr-only">Added: </span>
              {part.text}
            </ins>
          );
        }
        return part.text;
      })}
    </p>
  );
}

export function FixPanel({
  finding,
  onDecide,
}: {
  finding: Finding;
  onDecide: (action: FixDecision, text: string) => void;
}) {
  const [state, setState] = useState<FixState>({ kind: "closed" });

  function suggest() {
    setState({ kind: "loading" });
    requestFix(finding.id).then(
      (fix) => setState({ kind: "showing", fix }),
      (caught: ApiError) =>
        setState(
          caught.status === 422
            ? { kind: "failed", message: NO_SAFE_FIX, final: true }
            : { kind: "failed", message: caught.message, final: false },
        ),
    );
  }

  const close = () => setState({ kind: "closed" });

  if (state.kind === "closed") {
    return (
      <Button type="button" variant="outline" size="sm" onClick={suggest}>
        Suggest fix
      </Button>
    );
  }

  if (state.kind === "loading") {
    return (
      <p role="status" className="text-muted-foreground">
        Writing a fix…
      </p>
    );
  }

  if (state.kind === "failed") {
    return (
      <div className="flex w-full flex-col items-start gap-2">
        <p role="alert" className="border-l-2 border-destructive pl-2">
          {state.message}
        </p>
        {!state.final && (
          <Button type="button" variant="outline" size="sm" onClick={suggest}>
            Try again
          </Button>
        )}
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
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            disabled={!state.text.trim()}
            onClick={() => onDecide("edit_fix", state.text.trim())}
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

  const { fix } = state;
  return (
    <div className="flex w-full flex-col gap-2">
      <p className="font-medium">
        Suggested fix, attempt {fix.attempt} of {MAX_ATTEMPTS}
      </p>
      <TrackedChanges fix={fix} />
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => onDecide("accept_fix", fix.suggested)}
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
        {fix.attempt < MAX_ATTEMPTS && (
          <Button type="button" variant="outline" size="sm" onClick={suggest}>
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
