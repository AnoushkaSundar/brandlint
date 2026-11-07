"use client";

import { usePathname } from "next/navigation";
import { type ChangeEvent, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { DEMO_ACCOUNTS, switchTo } from "@/lib/demo";

// Lets a judge move through the workflow without signing out and in. Each choice is
// a real demo account, so what a role can't do is still refused by the API.
export function DemoSwitcher() {
  const { user } = useAuth();
  const pathname = usePathname();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = DEMO_ACCOUNTS.find((account) => account.email === user.email);

  async function change(event: ChangeEvent<HTMLSelectElement>) {
    const account = DEMO_ACCOUNTS.find((a) => a.email === event.target.value);
    if (!account) return;
    setPending(true);
    setError(null);
    try {
      await switchTo(account, pathname);
    } catch {
      setError("Couldn't switch. Try again.");
      setPending(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <label htmlFor="demo-role" className="text-sm text-muted-foreground">
        Viewing as
      </label>
      <select
        id="demo-role"
        value={current?.email ?? ""}
        disabled={pending}
        onChange={change}
        title={current?.does}
        className="h-8 rounded-md border bg-background px-2 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        {!current && <option value="">Choose a role</option>}
        {DEMO_ACCOUNTS.map((account) => (
          <option key={account.email} value={account.email}>
            {account.label}
          </option>
        ))}
      </select>
      {error && (
        <span role="alert" className="text-sm text-destructive">
          {error}
        </span>
      )}
    </div>
  );
}
