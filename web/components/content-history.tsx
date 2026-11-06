"use client";

import { useEffect, useState } from "react";

import { TrackedChanges } from "@/components/tracked-changes";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { type ContentVersion, STATE_LABELS } from "@/lib/content";
import {
  ACTION_LABELS,
  formatTime,
  getHistory,
  type History,
} from "@/lib/reviewDesk";

const SELECT_STYLE =
  "h-9 rounded-md border bg-background px-2 text-sm text-foreground";
// Comparing is quadratic in the number of words, so very long texts would hang the tab.
const MAX_COMPARED_WORDS = 4000;

function wordCount(text: string): number {
  return text.split(/\s+/).length;
}

function VersionPicker({
  id,
  label,
  versions,
  value,
  onChange,
}: {
  id: string;
  label: string;
  versions: readonly ContentVersion[];
  value: number;
  onChange: (version: number) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        className={SELECT_STYLE}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {versions.map((version) => (
          <option key={version.id} value={version.version}>
            Version {version.version}
          </option>
        ))}
      </select>
    </div>
  );
}

function CompareVersions({
  versions,
}: {
  versions: readonly ContentVersion[];
}) {
  const [from, setFrom] = useState(versions[1].version);
  const [to, setTo] = useState(versions[0].version);
  const before = versions.find((item) => item.version === from);
  const after = versions.find((item) => item.version === to);

  const tooLong =
    wordCount(before?.text ?? "") * wordCount(after?.text ?? "") >
    MAX_COMPARED_WORDS * MAX_COMPARED_WORDS;

  let body = <p>One of these versions is a file with no text to compare.</p>;
  if (before?.text && after?.text) {
    body = tooLong ? (
      <p>These versions are too long to compare here.</p>
    ) : (
      <TrackedChanges before={before.text} after={after.text} />
    );
  }

  return (
    <div className="mt-3 flex flex-col gap-3 text-sm">
      <div className="flex flex-wrap gap-4">
        <VersionPicker
          id="compare-from"
          label="Compare"
          versions={versions}
          value={from}
          onChange={setFrom}
        />
        <VersionPicker
          id="compare-to"
          label="With"
          versions={versions}
          value={to}
          onChange={setTo}
        />
      </div>
      {body}
    </div>
  );
}

export function ContentHistory({
  contentId,
  versions,
}: {
  contentId: string;
  versions: readonly ContentVersion[];
}) {
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    getHistory(contentId).then(
      (loaded) => {
        if (current) setHistory(loaded);
      },
      (caught: ApiError) => {
        if (current) setError(caught.message);
      },
    );
    return () => {
      current = false;
    };
  }, [contentId, versions.length]);

  return (
    <section aria-labelledby="record-heading" className="mt-8">
      <h2 id="record-heading" className="text-lg font-semibold">
        Review record
      </h2>

      {error && (
        <p
          role="alert"
          className="mt-3 rounded-lg border border-destructive p-3 text-sm text-destructive"
        >
          {error}
        </p>
      )}

      {history?.stamp && (
        <p className="mt-3 rounded-lg border p-3 text-sm">
          Published {formatTime(history.stamp.published_at)}: version{" "}
          {history.stamp.version}, checked against rulebook version{" "}
          {history.stamp.rulebook_version}. Approved by{" "}
          {history.stamp.approvers.join(", ")}.
        </p>
      )}

      {versions.length > 1 && <CompareVersions versions={versions} />}

      {history && history.decisions.length > 0 && (
        <>
          <h3 className="mt-5 font-medium">Decisions</h3>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {history.decisions.map((decision, index) => (
              <li key={index}>
                {ACTION_LABELS[decision.action]} on version {decision.version}:{" "}
                {decision.actor}, {formatTime(decision.created_at)}
                {decision.reason && (
                  <span className="text-muted-foreground">
                    {" "}
                    ({decision.reason})
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {history && history.states.length > 0 && (
        <>
          <h3 className="mt-5 font-medium">Workflow</h3>
          <ol className="mt-2 flex flex-col gap-1 text-sm">
            {history.states.map((entry, index) => (
              <li key={index}>
                {STATE_LABELS[entry.to_state]}: {entry.actor},{" "}
                {formatTime(entry.created_at)}
                {entry.reason && (
                  <span className="text-muted-foreground">
                    {" "}
                    ({entry.reason})
                  </span>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
