"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { CI_ENABLED } from "@/lib/navigation";
import {
  channelLabel,
  type ContentSummary,
  listContent,
  STATE_LABELS,
} from "@/lib/content";

export function ContentList() {
  const { user } = useAuth();
  const [items, setItems] = useState<ContentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fromCI, setFromCI] = useState(false);

  useEffect(() => {
    let current = true;
    listContent(fromCI ? "ci" : undefined).then(
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
  }, [fromCI]);

  const canSubmit = user.role === "creator";

  return (
    <div className="mx-auto w-full max-w-5xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Content</h1>
          <p className="mt-1 text-muted-foreground">
            Submit drafts and follow them through review and approval.
          </p>
        </div>
        {canSubmit && (
          <Link href="/content/new" className={buttonVariants()}>
            New content
          </Link>
        )}
      </div>

      {user.role !== "creator" && CI_ENABLED && (
        <div className="mt-4 flex items-center gap-2 text-sm">
          <label htmlFor="content-source">Show</label>
          <select
            id="content-source"
            value={fromCI ? "ci" : "all"}
            onChange={(event) => {
              setItems(null);
              setFromCI(event.target.value === "ci");
            }}
            className="h-9 rounded-md border bg-background px-2"
          >
            <option value="all">Submitted content</option>
            <option value="ci">Sent from CI</option>
          </select>
        </div>
      )}

      <div className="mt-6">
        {error && (
          <p
            role="alert"
            className="rounded-lg border border-destructive p-3 text-sm text-destructive"
          >
            {error}
          </p>
        )}
        {!error && items === null && (
          <p role="status" className="text-sm text-muted-foreground">
            Loading…
          </p>
        )}
        {items?.length === 0 && (
          <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
            {canSubmit
              ? "Nothing here yet. Submit your first draft to get it reviewed."
              : "Nothing has been submitted yet."}
          </p>
        )}
        {items && items.length > 0 && (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Submitted content</caption>
              <thead className="border-b bg-muted">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">
                    Title
                  </th>
                  <th scope="col" className="px-4 py-2 font-medium">
                    Channel
                  </th>
                  <th scope="col" className="px-4 py-2 font-medium">
                    Source
                  </th>
                  <th scope="col" className="px-4 py-2 font-medium">
                    State
                  </th>
                  <th scope="col" className="px-4 py-2 font-medium">
                    Submitted
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b last:border-b-0">
                    <td className="px-4 py-2">
                      <Link
                        href={`/content/${item.id}`}
                        className="font-medium underline underline-offset-2"
                      >
                        {item.title}
                      </Link>
                    </td>
                    <td className="px-4 py-2">{channelLabel(item.channel)}</td>
                    <td className="px-4 py-2">{item.source}</td>
                    <td className="px-4 py-2">{STATE_LABELS[item.state]}</td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      {new Date(item.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
