"use client";

import { Check, Circle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ErrorNotice, errorMessage } from "@/components/brand-ui";
import { Button } from "@/components/ui/button";
import { loadSampleGuidelines } from "@/lib/workspace";

// What a new workspace needs before its first review can run. Only for the admin of a
// sandbox that isn't set up yet.
export function OnboardingChecklist() {
  const { user, workspace, refreshWorkspace } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!workspace || workspace.kind !== "sandbox" || user.role !== "admin") {
    return null;
  }
  const { checklist } = workspace;
  if (Object.values(checklist).every(Boolean)) return null;

  const steps = [
    {
      done: checklist.guidelines,
      label: "Upload your brand guidelines",
      href: "/brand/rulebook",
    },
    {
      done: checklist.approved_rules,
      label: "Review and approve the rules",
      href: "/brand/rulebook",
    },
    { done: checklist.teammates, label: "Invite a teammate", href: "/people" },
    {
      done: checklist.first_draft,
      label: "Upload your first draft",
      href: "/content/new",
    },
  ];

  async function loadSample() {
    setBusy(true);
    setError(null);
    try {
      await loadSampleGuidelines();
      refreshWorkspace();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="onboarding-title"
      className="mb-6 rounded-xl border bg-background p-5"
    >
      <h2 id="onboarding-title" className="text-lg font-semibold">
        Set up {workspace.name}
      </h2>
      <ol className="mt-3 flex flex-col gap-2">
        {steps.map((step) => (
          <li key={step.label} className="flex items-center gap-2 text-sm">
            {step.done ? (
              <Check aria-label="Done" className="size-4 text-green-700" />
            ) : (
              <Circle
                aria-label="To do"
                className="size-4 text-muted-foreground"
              />
            )}
            {step.done ? (
              <span className="text-muted-foreground line-through">
                {step.label}
              </span>
            ) : (
              <Link href={step.href} className="underline underline-offset-2">
                {step.label}
              </Link>
            )}
          </li>
        ))}
      </ol>
      {!checklist.approved_rules && (
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t pt-4">
          <p className="text-sm text-muted-foreground">
            No guidelines yet? Start from the Tarnhollow sample, then edit it.
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={loadSample}
            disabled={busy}
          >
            {busy ? "Loading…" : "Load sample guidelines"}
          </Button>
        </div>
      )}
      <ErrorNotice message={error} />
    </section>
  );
}
