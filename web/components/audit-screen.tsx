"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { ROLES } from "@/lib/contracts";
import {
  type AuditEntry,
  type AuditPage,
  formatTime,
  getAudit,
} from "@/lib/reviewDesk";

const PAGE_SIZE = 25;
const ACTION_FILTERS = [
  { value: "", label: "Everything" },
  { value: "decision:", label: "Decisions" },
  { value: "state_change", label: "State changes" },
];
const SELECT_STYLE =
  "h-9 rounded-md border bg-background px-2 text-sm text-foreground";

function changeLabel(entry: AuditEntry): string {
  const value = (side: Record<string, unknown> | null) =>
    side ? Object.values(side)[0] : null;
  const before = value(entry.before);
  const after = value(entry.after);
  return before || after ? `${before ?? "none"} → ${after ?? "none"}` : "";
}

export function AuditScreen() {
  const [page, setPage] = useState<AuditPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState("");
  const [role, setRole] = useState("");
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    let current = true;
    getAudit({ action, role, limit: PAGE_SIZE, offset }).then(
      (loaded) => {
        if (current) {
          setPage(loaded);
          setError(null);
        }
      },
      (caught: ApiError) => {
        if (current) setError(caught.message);
      },
    );
    return () => {
      current = false;
    };
  }, [action, role, offset]);

  const total = page?.total ?? 0;

  return (
    <div className="mx-auto w-full max-w-5xl">
      <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
      <p className="mt-2 text-muted-foreground">
        Every decision, state change and rule change.
      </p>

      <div className="mt-4 flex flex-wrap gap-4">
        <div className="flex flex-col gap-1">
          <Label htmlFor="audit-action">Show</Label>
          <select
            id="audit-action"
            className={SELECT_STYLE}
            value={action}
            onChange={(event) => {
              setAction(event.target.value);
              setOffset(0);
            }}
          >
            {ACTION_FILTERS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="audit-role">Role</Label>
          <select
            id="audit-role"
            className={`${SELECT_STYLE} capitalize`}
            value={role}
            onChange={(event) => {
              setRole(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">All roles</option>
            {ROLES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-destructive p-3 text-sm text-destructive"
        >
          {error}
        </p>
      )}
      {!page && !error && (
        <p role="status" className="mt-4 text-sm text-muted-foreground">
          Loading…
        </p>
      )}
      {page?.items.length === 0 && (
        <p className="mt-6 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          Nothing matches these filters.
        </p>
      )}

      {page && page.items.length > 0 && (
        <>
          <div tabIndex={0} className="mt-4 overflow-x-auto rounded-lg border">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Audit log entries</caption>
              <thead className="border-b">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">
                    When
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Who
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Action
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Change
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Rulebook
                  </th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((entry) => (
                  <tr key={entry.id} className="border-b last:border-0">
                    <td className="px-3 py-2 whitespace-nowrap">
                      {formatTime(entry.created_at)}
                    </td>
                    <td className="px-3 py-2">
                      {entry.actor}{" "}
                      <span className="text-muted-foreground capitalize">
                        {entry.role}
                      </span>
                    </td>
                    <td className="px-3 py-2">{entry.action}</td>
                    <td className="px-3 py-2">{changeLabel(entry)}</td>
                    <td className="px-3 py-2">
                      {entry.rulebook_version ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center gap-3 text-sm">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Newer
            </Button>
            <p>
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Older
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
