"use client";

import { type FormEvent, useState } from "react";

import {
  ErrorNotice,
  SELECT_STYLE,
  SavedNotice,
  ScreenHeader,
  errorMessage,
  useLoaded,
} from "@/components/brand-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type CreatedToken,
  createToken,
  EXAMPLE_WORKFLOW,
  getCIPolicy,
  getTokens,
  type PolicySettings,
  revokeToken,
  saveCIPolicy,
} from "@/lib/ci";
import type { Severity } from "@/lib/contracts";

const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];

function PolicyForm({ initial }: { initial: PolicySettings }) {
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    setSaved(false);
    try {
      await saveCIPolicy({
        severity_threshold: String(form.get("severity")) as Severity,
        fail_on_unsure: form.get("unsure") === "on",
        ignore_rules: String(form.get("ignore"))
          .split(/[\s,]+/)
          .filter(Boolean),
        max_waiting_minutes: Number(form.get("minutes")),
      });
      setSaved(true);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  return (
    <form onSubmit={save} className="mt-4 grid gap-4 rounded-lg border bg-background p-4 sm:grid-cols-2">
      <div className="flex flex-col gap-2">
        <Label htmlFor="ci-severity">Fail a run on findings at or above</Label>
        <select id="ci-severity" name="severity" defaultValue={initial.severity_threshold} className={SELECT_STYLE}>
          {SEVERITIES.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="ci-minutes">Wait for a review up to (minutes)</Label>
        <Input id="ci-minutes" name="minutes" type="number" min={1} max={120} defaultValue={initial.max_waiting_minutes} />
      </div>
      <div className="flex items-center gap-2 sm:col-span-2">
        <input id="ci-unsure" name="unsure" type="checkbox" defaultChecked={initial.fail_on_unsure} className="size-4" />
        <Label htmlFor="ci-unsure">Also fail on findings the AI was unsure about</Label>
      </div>
      <div className="flex flex-col gap-2 sm:col-span-2">
        <Label htmlFor="ci-ignore">Rules to ignore (approved rule ids, separated by spaces or commas)</Label>
        <Input id="ci-ignore" name="ignore" defaultValue={initial.ignore_rules.join(", ")} />
      </div>
      <div className="sm:col-span-2">
        <Button type="submit">Save policy</Button>
      </div>
      <div className="sm:col-span-2">
        <ErrorNotice message={error} />
        {saved && <SavedNotice>Policy saved. It applies to every run, including ones already made.</SavedNotice>}
      </div>
    </form>
  );
}

function Tokens() {
  const { data, error, reload } = useLoaded(getTokens);
  const [created, setCreated] = useState<CreatedToken | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setProblem(null);
    try {
      const days = String(values.get("days")).trim();
      setCreated(await createToken(String(values.get("name")), days ? Number(days) : null));
      form.reset();
      reload();
    } catch (caught) {
      setProblem(errorMessage(caught));
    }
  }

  async function revoke(id: string) {
    setProblem(null);
    try {
      await revokeToken(id);
      reload();
    } catch (caught) {
      setProblem(errorMessage(caught));
    }
  }

  return (
    <>
      <form onSubmit={create} className="mt-4 flex flex-wrap items-end gap-3 rounded-lg border bg-background p-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="token-name">Name</Label>
          <Input id="token-name" name="name" required maxLength={120} placeholder="GitHub Action" />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="token-days">Expires in (days, optional)</Label>
          <Input id="token-days" name="days" type="number" min={1} max={365} />
        </div>
        <Button type="submit">Create token</Button>
      </form>
      <ErrorNotice message={problem ?? error} />
      {created && (
        <div role="status" className="mt-4 rounded-lg border border-amber-500 bg-amber-50 p-4 text-sm text-amber-950">
          <p className="font-semibold">Copy this token now. It is shown once and can&apos;t be seen again.</p>
          <code className="mt-2 block rounded bg-background p-2 break-all">{created.token}</code>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => setCreated(null)}>
            I&apos;ve copied it
          </Button>
        </div>
      )}
      <div className="mt-4 overflow-x-auto rounded-lg border">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Service tokens</caption>
          <thead className="border-b bg-muted">
            <tr>
              <th scope="col" className="p-3 font-medium">Name</th>
              <th scope="col" className="p-3 font-medium">Starts with</th>
              <th scope="col" className="p-3 font-medium">Last used</th>
              <th scope="col" className="p-3 font-medium">Status</th>
              <th scope="col" className="p-3 font-medium"><span className="sr-only">Revoke</span></th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((token) => (
              <tr key={token.id} className="border-b last:border-b-0">
                <td className="p-3">{token.name}</td>
                <td className="p-3"><code>{token.prefix}</code></td>
                <td className="p-3">{token.last_used_at ? new Date(token.last_used_at).toLocaleString() : "Never"}</td>
                <td className="p-3">{token.revoked_at ? "Revoked" : token.expires_at ? `Expires ${new Date(token.expires_at).toLocaleDateString()}` : "Active"}</td>
                <td className="p-3">
                  {!token.revoked_at && (
                    <Button variant="outline" size="sm" aria-label={`Revoke ${token.name}`} onClick={() => revoke(token.id)}>
                      Revoke
                    </Button>
                  )}
                </td>
              </tr>
            ))}
            {data?.length === 0 && (
              <tr>
                <td colSpan={5} className="p-3 text-muted-foreground">No tokens yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function CISettings() {
  const { data: policy, error } = useLoaded(getCIPolicy);

  return (
    <div className="mx-auto w-full max-w-4xl">
      <ScreenHeader
        title="CI settings"
        summary="What fails a pull request's check, and the tokens a CI job signs in with."
      />
      <h2 className="mt-8 text-xl font-semibold">Policy</h2>
      <ErrorNotice message={error} />
      {policy ? <PolicyForm initial={policy} /> : !error && <p role="status" className="mt-4 text-sm text-muted-foreground">Loading…</p>}

      <h2 className="mt-10 text-xl font-semibold">Service tokens</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        A token lets a CI job send copy for checking, and nothing else. Put it in your repo&apos;s secrets as BRANDLINT_TOKEN.
      </p>
      <Tokens />

      <h2 className="mt-10 text-xl font-semibold">Add it to a repo</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        An example workflow. GitHub blocks the merge when this check is a required status check in branch protection, not the action itself.
      </p>
      <pre className="mt-3 overflow-x-auto rounded-lg border bg-muted p-4 text-xs">{EXAMPLE_WORKFLOW}</pre>
    </div>
  );
}
