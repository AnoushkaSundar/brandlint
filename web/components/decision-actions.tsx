"use client";

import { useState } from "react";

import { ReasonForm } from "@/components/reason-form";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import type { DecisionAction } from "@/lib/contracts";
import type { DecisionInput } from "@/lib/workflow";

const REASON_ACTIONS = [
  {
    action: "override",
    button: "Override",
    label: "Why should this be overridden?",
    submit: "Submit override",
  },
  {
    action: "reject_override",
    button: "Reject override",
    label: "Why is this override rejected?",
    submit: "Reject",
  },
  {
    action: "resolve",
    button: "Resolve",
    label: "How was this settled?",
    submit: "Mark resolved",
  },
] as const;

export function DecisionActions({
  allowed,
  onDecide,
}: {
  allowed: readonly DecisionAction[];
  onDecide: (input: DecisionInput) => Promise<void>;
}) {
  const [opened, setOpened] = useState<DecisionAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const form = REASON_ACTIONS.find(({ action }) => action === opened);
  if (form) {
    return (
      <ReasonForm
        label={form.label}
        submitLabel={form.submit}
        onSubmit={(reason) => onDecide({ action: form.action, reason })}
        onCancel={() => setOpened(null)}
      />
    );
  }

  function confirm() {
    setBusy(true);
    setError(null);
    onDecide({ action: "confirm_override" }).catch((caught: ApiError) => {
      setError(caught.message);
      setBusy(false);
    });
  }

  return (
    <>
      {allowed.includes("confirm_override") && (
        <Button type="button" size="sm" disabled={busy} onClick={confirm}>
          Confirm override
        </Button>
      )}
      {REASON_ACTIONS.filter(({ action }) => allowed.includes(action)).map(
        ({ action, button }) => (
          <Button
            key={action}
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setOpened(action)}
          >
            {button}
          </Button>
        ),
      )}
      {error && (
        <p role="alert" className="w-full border-l-2 border-destructive pl-2">
          {error}
        </p>
      )}
    </>
  );
}
