"use client";

import Link from "next/link";
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
  type FactInput,
  type Impact,
  createFact,
  expiry,
  getFacts,
  updateFact,
} from "@/lib/admin";
import type { DataClass, Fact } from "@/lib/contracts";

const DATA_CLASSES: DataClass[] = [
  "public",
  "internal",
  "confidential",
  "restricted",
];

const BLANK: FactInput = {
  statement: "",
  value: "",
  source_doc: "",
  owner: "",
  valid_until: null,
  data_class: "public",
};

function inputFrom(fact: Fact): FactInput {
  return {
    statement: fact.statement,
    value: fact.value,
    source_doc: fact.source_doc,
    owner: fact.owner,
    valid_until: fact.valid_until ?? null,
    data_class: fact.data_class,
  };
}

function FactForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: FactInput;
  submitLabel: string;
  onSubmit: (fact: FactInput) => Promise<void>;
  onCancel: () => void;
}) {
  const [fact, setFact] = useState(initial);
  const [busy, setBusy] = useState(false);
  const field = (key: keyof FactInput) => ({
    id: `fact-${key}`,
    value: fact[key] ?? "",
    onChange: (
      event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => setFact({ ...fact, [key]: event.target.value || null }),
  });

  return (
    <form
      className="mt-4 grid gap-3 rounded-lg border p-4 sm:grid-cols-2"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        try {
          await onSubmit(fact);
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="flex flex-col gap-1 sm:col-span-2">
        <Label htmlFor="fact-statement">Statement</Label>
        <Textarea required {...field("statement")} />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="fact-value">Value</Label>
        <Input required {...field("value")} />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="fact-valid_until">Valid until</Label>
        <Input type="date" {...field("valid_until")} />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="fact-source_doc">Source document</Label>
        <Input required {...field("source_doc")} />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="fact-owner">Owner</Label>
        <Input required {...field("owner")} />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="fact-data_class">Data class</Label>
        <select
          id="fact-data_class"
          className={`${SELECT_STYLE} capitalize`}
          value={fact.data_class}
          onChange={(event) =>
            setFact({ ...fact, data_class: event.target.value as DataClass })
          }
        >
          {DATA_CLASSES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-end gap-2 sm:col-span-2">
        <Button type="submit" disabled={busy}>
          {submitLabel}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function ExpiryBadge({ validUntil }: { validUntil?: string | null }) {
  const state = expiry(validUntil);
  if (!state) return null;
  return (
    <span
      className={`ml-2 rounded px-1.5 py-0.5 text-xs font-medium ${
        state === "expired"
          ? "bg-destructive text-white"
          : "bg-amber-200 text-amber-950 dark:bg-amber-300"
      }`}
    >
      {state === "expired" ? "Expired" : "Expires soon"}
    </span>
  );
}

function ImpactNotice({
  factId,
  impact,
}: {
  factId: string;
  impact: Impact[];
}) {
  return (
    <SavedNotice>
      Saved a new version of {factId}.{" "}
      {impact.length === 0
        ? "No reviewed piece cites it."
        : `${impact.length} ${impact.length === 1 ? "piece cites" : "pieces cite"} the old wording and may need another review:`}
      {impact.length > 0 && (
        <ul className="mt-2 list-disc pl-5">
          {impact.map((item) => (
            <li key={`${item.content_id}-${item.claim_text}`}>
              <Link className="underline" href={`/content/${item.content_id}`}>
                “{item.claim_text}”
              </Link>{" "}
              <span className="text-muted-foreground">({item.state})</span>
            </li>
          ))}
        </ul>
      )}
    </SavedNotice>
  );
}

export function FactsScreen() {
  const { data: facts, error: loadError, reload } = useLoaded(getFacts);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [impact, setImpact] = useState<{ id: string; items: Impact[] } | null>(
    null,
  );

  async function save(fact: FactInput, id?: string) {
    setError(null);
    setImpact(null);
    try {
      if (id) {
        const saved = await updateFact(id, fact);
        setImpact({ id, items: saved.impact });
      } else {
        await createFact(fact);
      }
      setEditing(null);
      reload();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  const list = facts ?? [];
  const attention = list.filter((fact) => expiry(fact.valid_until)).length;

  return (
    <div className="mx-auto w-full max-w-5xl">
      <ScreenHeader
        title="Facts"
        summary="Approved claims that content can cite. An edit adds a version, so past reviews keep what they were checked against."
      />
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button type="button" onClick={() => setEditing("new")}>
          Add a fact
        </Button>
        {attention > 0 && (
          <p className="text-sm">
            {attention} {attention === 1 ? "fact needs" : "facts need"} a new
            date or a new source.
          </p>
        )}
      </div>

      {editing === "new" && (
        <FactForm
          initial={BLANK}
          submitLabel="Add fact"
          onSubmit={(fact) => save(fact)}
          onCancel={() => setEditing(null)}
        />
      )}
      <ErrorNotice message={error ?? loadError} />
      {impact && <ImpactNotice factId={impact.id} impact={impact.items} />}

      {facts && list.length === 0 && (
        <p className="mt-6 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No facts yet.
        </p>
      )}
      <ul className="mt-4 flex flex-col gap-3">
        {list.map((fact) => (
          <li
            key={fact.id}
            className={`rounded-lg border p-4 ${expiry(fact.valid_until) === "expired" ? "border-destructive" : ""}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  {fact.id}{" "}
                  <span className="font-normal text-muted-foreground">
                    v{fact.version} · {fact.data_class}
                  </span>
                  <ExpiryBadge validUntil={fact.valid_until} />
                </p>
                <p className="mt-1 text-sm">{fact.statement}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {fact.value} · {fact.source_doc} · {fact.owner}
                  {fact.valid_until ? ` · valid until ${fact.valid_until}` : ""}
                </p>
              </div>
              {editing !== fact.id && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  aria-label={`Edit ${fact.id}`}
                  onClick={() => setEditing(fact.id)}
                >
                  Edit
                </Button>
              )}
            </div>
            {editing === fact.id && (
              <FactForm
                initial={inputFrom(fact)}
                submitLabel="Save new version"
                onSubmit={(input) => save(input, fact.id)}
                onCancel={() => setEditing(null)}
              />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
