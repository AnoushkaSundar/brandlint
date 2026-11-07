"use client";

import { useState } from "react";

import {
  ErrorNotice,
  SavedNotice,
  ScreenHeader,
  SELECT_STYLE,
  errorMessage,
  useLoaded,
} from "@/components/brand-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  approveRules,
  editDraft,
  getDrafts,
  getRulebook,
  ingestGuideline,
  rejectDraft,
} from "@/lib/admin";
import type { Rule, Severity } from "@/lib/contracts";

const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];

async function loadRulebook(): Promise<Rule[]> {
  try {
    return await getRulebook();
  } catch {
    // An empty rulebook is normal before the first guideline is approved.
    return [];
  }
}

function DraftCard({
  rule,
  conflictsWith,
  selected,
  onSelect,
  onChanged,
  onError,
}: {
  rule: Rule;
  conflictsWith: string[];
  selected: boolean;
  onSelect: (selected: boolean) => void;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(rule.text);
  const [severity, setSeverity] = useState<Severity>(rule.severity);
  const [busy, setBusy] = useState(false);

  async function act(work: () => Promise<unknown>) {
    setBusy(true);
    try {
      await work();
      setEditing(false);
      onChanged();
    } catch (caught) {
      onError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const checkbox = `select-${rule.id}`;
  return (
    <li
      className={`rounded-lg border p-4 ${conflictsWith.length ? "border-destructive" : ""}`}
    >
      <div className="flex flex-wrap items-start gap-3">
        <input
          id={checkbox}
          type="checkbox"
          className="mt-1 size-4"
          checked={selected}
          onChange={(event) => onSelect(event.target.checked)}
        />
        <div className="min-w-0 flex-1">
          <label htmlFor={checkbox} className="font-medium">
            {rule.id}{" "}
            <span className="font-normal text-muted-foreground">
              {rule.clause_ref} · {rule.type.replace("_", " ")} ·{" "}
              {rule.severity}
            </span>
          </label>
          {!editing && <p className="mt-1 text-sm">{rule.text}</p>}
          {rule.required_text && !editing && (
            <p className="mt-1 text-sm text-muted-foreground">
              Must include: “{rule.required_text}”
            </p>
          )}
          {conflictsWith.length > 0 && (
            <p className="mt-2 text-sm text-destructive">
              Contradicts {conflictsWith.join(", ")}. Reject or edit one before
              approving both.
            </p>
          )}
        </div>
      </div>

      {editing && (
        <form
          className="mt-3 flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            act(() =>
              editDraft(rule.id, {
                text,
                severity,
                channel_scope: rule.channel_scope,
                required_text: rule.required_text ?? null,
              }),
            );
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor={`text-${rule.id}`}>Rule text</Label>
            <Textarea
              id={`text-${rule.id}`}
              value={text}
              required
              onChange={(event) => setText(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`severity-${rule.id}`}>Severity</Label>
            <select
              id={`severity-${rule.id}`}
              className={`${SELECT_STYLE} w-40 capitalize`}
              value={severity}
              onChange={(event) => setSeverity(event.target.value as Severity)}
            >
              {SEVERITIES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={busy}>
              Save draft
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setEditing(false)}
            >
              Cancel
            </Button>
          </div>
        </form>
      )}

      {!editing && (
        <div className="mt-3 flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setEditing(true)}
          >
            Edit
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => act(() => rejectDraft(rule.id))}
          >
            Reject
          </Button>
        </div>
      )}
    </li>
  );
}

export function RulebookScreen() {
  const drafts = useLoaded(getDrafts);
  const rulebook = useLoaded(loadRulebook);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  function refresh() {
    drafts.reload();
    rulebook.reload();
  }

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const job = await ingestGuideline(file);
      if (job.status === "failed") {
        setError(job.error ?? "The guideline couldn't be read.");
      } else {
        const count = job.result?.rules.length ?? 0;
        setNotice(
          `Read ${count} rules from ${file.name}. Nothing is live until you approve it.`,
        );
        setSelected(new Set());
      }
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { version } = await approveRules([...selected]);
      setNotice(`Approved. The rulebook is now version ${version}.`);
      setSelected(new Set());
      refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const draftList = drafts.data?.drafts ?? [];
  const live = rulebook.data ?? [];
  const conflicts = drafts.data?.conflicts ?? [];
  const partners = (id: string) =>
    conflicts.flatMap((pair) =>
      pair.includes(id) ? pair.filter((other) => other !== id) : [],
    );

  return (
    <div className="mx-auto w-full max-w-4xl">
      <ScreenHeader
        title="Rulebook"
        summary="Read a guideline into draft rules, then approve them as a new rulebook version."
      />

      <section aria-labelledby="ingest-heading" className="mt-6">
        <h2 id="ingest-heading" className="text-lg font-semibold">
          Read a guideline
        </h2>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="guideline-file">PDF, DOCX or text file</Label>
            <Input
              id="guideline-file"
              type="file"
              accept=".pdf,.docx,.txt,.md"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <Button type="button" disabled={!file || busy} onClick={upload}>
            {busy ? "Working…" : "Read guideline"}
          </Button>
        </div>
      </section>

      <ErrorNotice message={error ?? drafts.error} />
      {notice && <SavedNotice>{notice}</SavedNotice>}

      <section aria-labelledby="drafts-heading" className="mt-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="drafts-heading" className="text-lg font-semibold">
            Drafts waiting for approval
          </h2>
          {draftList.length > 0 && (
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() =>
                  setSelected(
                    selected.size === draftList.length
                      ? new Set()
                      : new Set(draftList.map((rule) => rule.id)),
                  )
                }
              >
                {selected.size === draftList.length
                  ? "Clear selection"
                  : "Select all"}
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={selected.size === 0 || busy}
                onClick={approve}
              >
                Approve {selected.size || ""} as version {drafts.data?.version}
              </Button>
            </div>
          )}
        </div>
        {drafts.data && draftList.length === 0 && (
          <p className="mt-3 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
            No drafts. Read a guideline to propose rules.
          </p>
        )}
        <ul className="mt-3 flex flex-col gap-3">
          {draftList.map((rule) => (
            <DraftCard
              key={`${rule.id}-${rule.text}-${rule.severity}`}
              rule={rule}
              conflictsWith={partners(rule.id)}
              selected={selected.has(rule.id)}
              onSelect={(on) => {
                const next = new Set(selected);
                if (on) next.add(rule.id);
                else next.delete(rule.id);
                setSelected(next);
              }}
              onChanged={() => {
                const next = new Set(selected);
                next.delete(rule.id);
                setSelected(next);
                refresh();
              }}
              onError={setError}
            />
          ))}
        </ul>
      </section>

      <section aria-labelledby="live-heading" className="mt-8">
        <h2 id="live-heading" className="text-lg font-semibold">
          Rules in force
          {live.length > 0 && (
            <span className="font-normal text-muted-foreground">
              {" "}
              · version {Math.max(...live.map((rule) => rule.version))}
            </span>
          )}
        </h2>
        {rulebook.data && live.length === 0 && (
          <p className="mt-3 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
            No approved rules yet.
          </p>
        )}
        {live.length > 0 && (
          <div tabIndex={0} className="mt-3 overflow-x-auto rounded-lg border">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Approved rules</caption>
              <thead className="border-b">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Rule
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Clause
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Text
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Severity
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Since
                  </th>
                </tr>
              </thead>
              <tbody>
                {live.map((rule) => (
                  <tr key={rule.id} className="border-b last:border-0">
                    <td className="px-3 py-2 whitespace-nowrap">{rule.id}</td>
                    <td className="px-3 py-2">{rule.clause_ref}</td>
                    <td className="px-3 py-2">{rule.text}</td>
                    <td className="px-3 py-2 capitalize">{rule.severity}</td>
                    <td className="px-3 py-2">v{rule.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
