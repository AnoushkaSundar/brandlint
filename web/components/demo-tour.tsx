"use client";

import { ArrowLeft, ArrowRight, Compass, Lightbulb, Minus, X } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import {
  accountFor,
  hrefFor,
  readTour,
  saveTour,
  switchTo,
  TOUR,
} from "@/lib/demo";

// A guided tour docked bottom-left, clear of the findings column, so a judge can
// follow each instruction on the real screen. Moving on switches to the person who does the
// next step and opens the exact page.
export function DemoTour() {
  const { user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  // Only rendered after sign-in, in the browser, so storage is safe to read here.
  const [state, setState] = useState(readTour);
  const [target, setTarget] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const step = TOUR[state.step];
  const last = state.step === TOUR.length - 1;
  const account = accountFor(step.role);

  useEffect(() => {
    let current = true;
    hrefFor(step.place).then(
      (href) => current && setTarget(href),
      () => current && setTarget(null),
    );
    return () => {
      current = false;
    };
  }, [step]);

  const here = user.role === step.role && target === pathname;

  function update(next: { step: number; open: boolean }) {
    saveTour(next.step, next.open);
    setState(next);
  }

  async function goTo(index: number) {
    const next = TOUR[index];
    update({ step: index, open: true });
    setError(null);
    setBusy(true);
    try {
      const href = await hrefFor(next.place);
      if (user.role === next.role) {
        router.push(href);
        setBusy(false);
      } else {
        await switchTo(accountFor(next.role), href);
      }
    } catch {
      setError("Couldn't open that step. Try again.");
      setBusy(false);
    }
  }

  if (!state.open) {
    return (
      <Button size="sm" onClick={() => update({ ...state, open: true })}>
        <Compass aria-hidden="true" />
        Guided tour
      </Button>
    );
  }

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => update({ ...state, open: false })}>
        <Compass aria-hidden="true" />
        Hide tour
      </Button>
      <aside
        aria-label="Guided tour"
        className="fixed bottom-4 left-4 z-40 flex max-h-[calc(100svh-6rem)] w-[min(26rem,calc(100vw-2rem))] flex-col rounded-xl border bg-background text-sm shadow-xl"
      >
        <div className="flex items-start justify-between gap-2 border-b px-4 py-3">
          <div>
            <p className="text-xs text-muted-foreground">
              Step {state.step + 1} of {TOUR.length} · as {account.label}
            </p>
            <h2 className="mt-0.5 text-base font-semibold">{step.title}</h2>
          </div>
          <div className="flex gap-1">
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label="Minimise the tour"
              onClick={() => update({ ...state, open: false })}
            >
              <Minus aria-hidden="true" />
            </Button>
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label="End the tour"
              onClick={() => update({ step: 0, open: false })}
            >
              <X aria-hidden="true" />
            </Button>
          </div>
        </div>
        <div
          className="h-1 bg-muted"
          role="progressbar"
          aria-label="Tour progress"
          aria-valuemin={1}
          aria-valuemax={TOUR.length}
          aria-valuenow={state.step + 1}
        >
          <div
            className="h-1 bg-primary transition-all"
            style={{ width: `${((state.step + 1) / TOUR.length) * 100}%` }}
          />
        </div>

        <div className="flex flex-col gap-3 overflow-y-auto px-4 py-3">
          <p>{step.see}</p>
          {here || busy ? (
            <div>
              <p className="font-medium">Try this</p>
              <ol className="mt-1 list-decimal space-y-1 pl-5">
                {step.steps.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ol>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed p-3">
              <p>
                This step happens{" "}
                {user.role === step.role ? "on another page" : `as ${account.person}`}.
              </p>
              <Button className="mt-2" size="sm" onClick={() => goTo(state.step)}>
                {user.role === step.role ? "Take me there" : `Switch to ${account.label}`}
              </Button>
            </div>
          )}
          <p className="flex gap-2 rounded-lg bg-muted p-3 text-muted-foreground">
            <Lightbulb aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>
              <span className="font-medium text-foreground">Why it matters: </span>
              {step.why}
            </span>
          </p>
          {last && (
            <p className="text-muted-foreground">
              That&apos;s the whole workflow. Use &ldquo;Viewing as&rdquo; at the top to
              explore freely as any role.
            </p>
          )}
          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t px-4 py-3">
          <Button
            size="sm"
            variant="ghost"
            disabled={state.step === 0 || busy}
            onClick={() => goTo(state.step - 1)}
          >
            <ArrowLeft aria-hidden="true" />
            Back
          </Button>
          {last ? (
            <Button size="sm" disabled={busy} onClick={() => goTo(0)}>
              Start again
            </Button>
          ) : (
            <Button size="sm" disabled={busy} onClick={() => goTo(state.step + 1)}>
              {busy
                ? "Opening…"
                : TOUR[state.step + 1].role === user.role
                  ? "Next"
                  : `Next: ${accountFor(TOUR[state.step + 1].role).label}`}
              <ArrowRight aria-hidden="true" />
            </Button>
          )}
        </div>
      </aside>
    </>
  );
}
