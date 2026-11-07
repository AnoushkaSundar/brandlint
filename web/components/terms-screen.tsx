"use client";

import { useState } from "react";

import {
  ErrorNotice,
  ScreenHeader,
  errorMessage,
  useLoaded,
} from "@/components/brand-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type TermInput, getTerms, saveTerm } from "@/lib/admin";
import type { Term } from "@/lib/contracts";

function TermForm({
  term,
  onSaved,
  onCancel,
}: {
  term?: Term;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const prefix = term ? `term-${term.id}` : "term-new";
  const [preferred, setPreferred] = useState(term?.preferred ?? "");
  const [banned, setBanned] = useState(term?.banned.join(", ") ?? "");
  const [renamedFrom, setRenamedFrom] = useState(term?.renamed_from ?? "");
  const [ruleId, setRuleId] = useState(term?.rule_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    const input: TermInput = {
      preferred,
      banned: banned
        .split(",")
        .map((word) => word.trim())
        .filter(Boolean),
      renamed_from: renamedFrom.trim() || null,
      rule_id: ruleId.trim() || null,
    };
    try {
      await saveTerm(input, term?.id);
      onSaved();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="mt-3 grid gap-3 rounded-lg border p-4 sm:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${prefix}-preferred`}>Preferred term</Label>
        <Input
          id={`${prefix}-preferred`}
          required
          value={preferred}
          onChange={(event) => setPreferred(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${prefix}-banned`}>
          Banned words, comma separated
        </Label>
        <Input
          id={`${prefix}-banned`}
          value={banned}
          onChange={(event) => setBanned(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${prefix}-renamed`}>Old product name</Label>
        <Input
          id={`${prefix}-renamed`}
          value={renamedFrom}
          onChange={(event) => setRenamedFrom(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${prefix}-rule`}>Rule it enforces</Label>
        <Input
          id={`${prefix}-rule`}
          placeholder="R-TERM-01"
          value={ruleId}
          onChange={(event) => setRuleId(event.target.value)}
        />
      </div>
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" disabled={busy}>
          {term ? "Save term" : "Add term"}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
      <div className="sm:col-span-2">
        <ErrorNotice message={error} />
      </div>
    </form>
  );
}

export function TermsScreen() {
  const { data: terms, error, reload } = useLoaded(getTerms);
  const [editing, setEditing] = useState<string | "new" | null>(null);

  function saved() {
    setEditing(null);
    reload();
  }

  const list = terms ?? [];
  return (
    <div className="mx-auto w-full max-w-4xl">
      <ScreenHeader
        title="Terms"
        summary="Preferred words, the words they replace, and old product names."
      />
      <div className="mt-4">
        <Button type="button" onClick={() => setEditing("new")}>
          Add a term
        </Button>
      </div>
      {editing === "new" && (
        <TermForm onSaved={saved} onCancel={() => setEditing(null)} />
      )}
      <ErrorNotice message={error} />
      {terms && list.length === 0 && (
        <p className="mt-6 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No terms yet.
        </p>
      )}
      <ul className="mt-4 flex flex-col gap-3">
        {list.map((term) => (
          <li key={term.id} className="rounded-lg border p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1 text-sm">
                <p className="text-base font-medium">
                  {term.preferred}{" "}
                  <span className="text-sm font-normal text-muted-foreground">
                    {term.id}
                    {term.rule_id ? ` · ${term.rule_id}` : ""}
                  </span>
                </p>
                {term.banned.length > 0 && (
                  <p className="mt-1">
                    Instead of:{" "}
                    {term.banned.map((word) => `“${word}”`).join(", ")}
                  </p>
                )}
                {term.renamed_from && (
                  <p className="mt-1 text-muted-foreground">
                    Renamed from {term.renamed_from}
                  </p>
                )}
              </div>
              {editing !== term.id && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  aria-label={`Edit ${term.preferred}`}
                  onClick={() => setEditing(term.id)}
                >
                  Edit
                </Button>
              )}
            </div>
            {editing === term.id && (
              <TermForm
                term={term}
                onSaved={saved}
                onCancel={() => setEditing(null)}
              />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
