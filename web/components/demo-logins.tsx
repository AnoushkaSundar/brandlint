"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { DEMO_ACCOUNTS, type DemoAccount, switchTo } from "@/lib/demo";

// One-click sign-in for the public demo, so nobody needs a password.
export function DemoLogins({ next }: { next: string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function signIn(account: DemoAccount) {
    setBusy(account.email);
    setError(null);
    try {
      await switchTo(account, account.role === "creator" ? next : "/content");
    } catch {
      setError("Couldn't sign in. Try again in a moment.");
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="demo-heading" className="mt-6 border-t pt-6">
      <h2 id="demo-heading" className="text-sm font-medium">
        Try the demo
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Start as the creator. Once you&apos;re in, use the Demo guide to switch
        roles.
      </p>
      <div className="mt-3 flex flex-col gap-2">
        {DEMO_ACCOUNTS.map((account) => (
          <Button
            key={account.email}
            variant={account.role === "creator" ? "default" : "outline"}
            disabled={busy !== null}
            onClick={() => signIn(account)}
            className="justify-start"
          >
            {busy === account.email ? "Signing in…" : `Continue as ${account.label}`}
          </Button>
        ))}
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      )}
    </section>
  );
}
