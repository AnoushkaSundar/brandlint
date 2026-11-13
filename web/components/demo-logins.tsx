"use client";

import { ArrowRight } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { DEMO_ACCOUNTS, accountFor, saveTour, switchTo, TOUR } from "@/lib/demo";

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
      {/* /judge/ is served by the proxy, not by Next, so this is a plain link, not <Link>. */}
      <a
        href="/judge/"
        className="text-center text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        Judge&apos;s guide and sample files
      </a>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

// One-click role picker: jump straight into any demo account without credentials.
export function DemoRolePicker() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function signInAs(email: string) {
    setBusy(email);
    setError(null);
    try {
      const account = DEMO_ACCOUNTS.find((a) => a.email === email);
      if (!account) throw new Error("unknown account");
      await switchTo(account, "/content");
    } catch {
      setError("Couldn't sign in. Try again.");
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {DEMO_ACCOUNTS.map((account) => (
        <button
          key={account.email}
          disabled={busy !== null}
          onClick={() => signInAs(account.email)}
          className="flex w-full items-center justify-between rounded-lg border px-4 py-3 text-left text-sm hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50"
        >
          <div>
            <span className="font-medium">{account.label}</span>
            <span className="ml-2 text-muted-foreground">{account.person}</span>
          </div>
          {busy === account.email ? (
            <span className="text-xs text-muted-foreground">Signing in…</span>
          ) : (
            <ArrowRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          )}
        </button>
      ))}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
