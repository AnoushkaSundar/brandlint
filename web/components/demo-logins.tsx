"use client";

import { ArrowRight } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { accountFor, saveTour, switchTo, TOUR } from "@/lib/demo";

// The public demo's only way in: no form, no password. It signs in as the creator and
// starts the guided tour on its first page.
export function StartDemo() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      saveTour(0, true);
      const first = TOUR[0];
      await switchTo(accountFor(first.role), "/content");
    } catch {
      setError("Couldn't start the demo. Try again in a moment.");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <ul className="space-y-2 text-sm text-muted-foreground">
        <li>A short guided tour, about five minutes.</li>
        <li>You&apos;ll play each person in the workflow, from writer to legal.</li>
        <li>Everything is real: real AI checks, and real permissions.</li>
      </ul>
      <Button size="lg" disabled={busy} onClick={start}>
        {busy ? "Starting…" : "Start the demo"}
        <ArrowRight aria-hidden="true" />
      </Button>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
