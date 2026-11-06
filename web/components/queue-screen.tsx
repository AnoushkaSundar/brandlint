"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SEVERITY_MARK } from "@/components/review-document";
import { ApiError } from "@/lib/api";
import { channelLabel } from "@/lib/content";
import { CHECK_LABELS, SEVERITY_LABELS } from "@/lib/findingLabels";
import { getQueue, type Queue, type QueueItem } from "@/lib/reviewDesk";
import { cn } from "@/lib/utils";

const KIND_LABELS: Record<QueueItem["kind"], string> = {
  unsure: "Needs a decision",
  override: "Override to check",
  fix: "Fix to sign off",
};

function Item({ item }: { item: QueueItem }) {
  return (
    <li className="flex flex-col gap-1 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "rounded-sm px-1.5 font-medium text-foreground underline decoration-2 underline-offset-2",
            SEVERITY_MARK[item.severity],
          )}
        >
          {SEVERITY_LABELS[item.severity]}
        </span>
        <span className="font-medium">{KIND_LABELS[item.kind]}</span>
        <span className="text-muted-foreground">
          {CHECK_LABELS[item.check]}
        </span>
      </div>
      <p>{item.explanation}</p>
      {item.kind === "override" && item.reason && (
        <p>Creator&apos;s reason: {item.reason}</p>
      )}
      {item.fix_text && <p>Wording: {item.fix_text}</p>}
      <Link
        href={`/content/${item.content_id}/review`}
        className="underline underline-offset-2"
      >
        {item.title}
      </Link>
    </li>
  );
}

export function QueueScreen() {
  const [queue, setQueue] = useState<Queue | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    getQueue().then(
      (loaded) => {
        if (current) setQueue(loaded);
      },
      (caught: ApiError) => {
        if (current) setError(caught.message);
      },
    );
    return () => {
      current = false;
    };
  }, []);

  const empty = queue?.items.length === 0 && queue.ready.length === 0;

  return (
    <div className="mx-auto w-full max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">Review queue</h1>
      <p className="mt-2 text-muted-foreground">
        UNSURE findings, pending overrides and fixes to sign off, most
        serious first.
      </p>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-destructive p-3 text-sm text-destructive"
        >
          {error}
        </p>
      )}
      {!queue && !error && (
        <p role="status" className="mt-4 text-sm text-muted-foreground">
          Loading…
        </p>
      )}
      {empty && (
        <p className="mt-6 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          Nothing is waiting for you.
        </p>
      )}

      {queue && queue.items.length > 0 && (
        <section aria-labelledby="decisions-heading" className="mt-6">
          <h2 id="decisions-heading" className="text-lg font-semibold">
            Decisions needed
          </h2>
          <ul className="mt-3 flex flex-col gap-2">
            {queue.items.map((item) => (
              <Item key={`${item.content_id}-${item.finding_id}`} item={item} />
            ))}
          </ul>
        </section>
      )}

      {queue && queue.ready.length > 0 && (
        <section aria-labelledby="ready-heading" className="mt-6">
          <h2 id="ready-heading" className="text-lg font-semibold">
            Ready for review
          </h2>
          <ul className="mt-3 flex flex-col gap-2 text-sm">
            {queue.ready.map((item) => (
              <li key={item.id} className="rounded-lg border p-3">
                <Link
                  href={`/content/${item.id}/review`}
                  className="underline underline-offset-2"
                >
                  {item.title}
                </Link>{" "}
                <span className="text-muted-foreground">
                  {channelLabel(item.channel)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
