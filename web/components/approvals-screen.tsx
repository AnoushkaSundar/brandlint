"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ApiError } from "@/lib/api";
import {
  channelLabel,
  type ContentSummary,
  listContent,
  STATE_LABELS,
} from "@/lib/content";
import type { ContentState, Role } from "@/lib/contracts";

const WAITING_ON: Partial<Record<Role, ContentState>> = {
  manager: "manager_approval",
  legal: "legal_signoff",
};

export function ApprovalsScreen() {
  const { user } = useAuth();
  const [items, setItems] = useState<ContentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    listContent().then(
      (loaded) => {
        if (current) setItems(loaded);
      },
      (caught: ApiError) => {
        if (current) setError(caught.message);
      },
    );
    return () => {
      current = false;
    };
  }, []);

  const waiting = items?.filter(
    (item) => item.state === WAITING_ON[user.role],
  );

  return (
    <div className="mx-auto w-full max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">Approvals</h1>
      <p className="mt-2 text-muted-foreground">
        Pieces waiting for your approval or sign-off.
      </p>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-destructive p-3 text-sm text-destructive"
        >
          {error}
        </p>
      )}
      {!items && !error && (
        <p role="status" className="mt-4 text-sm text-muted-foreground">
          Loading…
        </p>
      )}
      {waiting?.length === 0 && (
        <p className="mt-6 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          Nothing is waiting for you.
        </p>
      )}
      {waiting && waiting.length > 0 && (
        <ul className="mt-6 flex flex-col gap-2 text-sm">
          {waiting.map((item) => (
            <li key={item.id} className="rounded-lg border p-3">
              <Link
                href={`/content/${item.id}/review`}
                className="underline underline-offset-2"
              >
                {item.title}
              </Link>{" "}
              <span className="text-muted-foreground">
                {channelLabel(item.channel)}, {STATE_LABELS[item.state]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
