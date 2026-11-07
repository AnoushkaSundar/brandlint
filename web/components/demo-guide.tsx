"use client";

import { Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  accountFor,
  DEMO_ACCOUNTS,
  GUIDE,
  type GuideStep,
  switchTo,
} from "@/lib/demo";

const DONE_KEY = "brandlint-demo-done";

function readDone(): string[] {
  try {
    return JSON.parse(window.localStorage.getItem(DONE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function saveDone(done: string[]): void {
  try {
    window.localStorage.setItem(DONE_KEY, JSON.stringify(done));
  } catch {
    // Progress is a convenience. The guide works without it.
  }
}

// The workflow as a checklist. Each step signs in as the role it needs, so a judge
// sees what each person can and can't do.
export function DemoGuide() {
  const { user } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  // The list only renders once the sheet opens, in the browser, so reading storage
  // here can't cause a mismatch with the server's render.
  const [done, setDone] = useState<string[]>(() =>
    typeof window === "undefined" ? [] : readDone(),
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function go(step: GuideStep) {
    const next = Array.from(new Set([...done, step.id]));
    setDone(next);
    saveDone(next);
    setError(null);
    if (user.role === step.role) {
      setOpen(false);
      router.push(step.href);
      return;
    }
    setBusy(step.id);
    try {
      await switchTo(accountFor(step.role), step.href);
    } catch {
      setError("Couldn't switch role. Try again.");
      setBusy(null);
    }
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger render={<Button variant="outline" size="sm" />}>
        Demo guide
      </SheetTrigger>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Try the workflow</SheetTitle>
          <SheetDescription>
            Each step switches to the person who does it. The roles are real:
            what a role can&apos;t do is refused.
          </SheetDescription>
        </SheetHeader>
        <ol className="flex flex-col gap-3 px-4">
          {GUIDE.map((step, index) => {
            const label = accountFor(step.role).label;
            const finished = done.includes(step.id);
            return (
              <li key={step.id} className="rounded-lg border p-3">
                <div className="flex items-start gap-3">
                  <span
                    aria-hidden="true"
                    className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border text-xs"
                  >
                    {finished ? <Check className="size-3.5" /> : index + 1}
                  </span>
                  <div className="flex-1">
                    <p className="font-medium">
                      {step.title}{" "}
                      <span className="text-xs font-normal text-muted-foreground">
                        as {label}
                      </span>
                      {finished && <span className="sr-only"> (done)</span>}
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {step.body}
                    </p>
                    <Button
                      className="mt-2"
                      size="sm"
                      variant={user.role === step.role ? "default" : "outline"}
                      disabled={busy !== null}
                      onClick={() => go(step)}
                    >
                      {busy === step.id
                        ? "Switching…"
                        : user.role === step.role
                          ? "Go"
                          : `Go as ${label}`}
                    </Button>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
        {error && (
          <p role="alert" className="px-4 text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="px-4 pb-6">
          <h2 className="mt-2 text-sm font-medium">Who does what</h2>
          <dl className="mt-2 flex flex-col gap-2 text-sm">
            {DEMO_ACCOUNTS.map((account) => (
              <div key={account.role}>
                <dt className="font-medium">{account.label}</dt>
                <dd className="text-muted-foreground">{account.does}</dd>
              </div>
            ))}
          </dl>
        </div>
      </SheetContent>
    </Sheet>
  );
}
