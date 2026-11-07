"use client";

import Link from "next/link";
import { useState } from "react";

import {
  ErrorNotice,
  SavedNotice,
  ScreenHeader,
  errorMessage,
  useLoaded,
} from "@/components/brand-ui";
import { TrackedChanges } from "@/components/tracked-changes";
import { Button } from "@/components/ui/button";
import type { Proposal } from "@/lib/contracts";
import { decideProposal, getProposals, runGovernance } from "@/lib/governance";

const KIND_LABELS: Record<Proposal["kind"], string> = {
  amendment: "Rewrite the rule",
  anchor: "Add an example",
  term: "Change a term",
  severity: "Change the severity",
};

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function ProposalCard({
  proposal,
  busy,
  onDecide,
}: {
  proposal: Proposal;
  busy: boolean;
  onDecide: (status: "approved" | "rejected") => void;
}) {
  const gate = proposal.eval;
  const headingId = `proposal-${proposal.id}`;
  return (
    <li className="rounded-lg border p-4">
      <article aria-labelledby={headingId}>
        <h2 id={headingId} className="font-medium">
          {proposal.rule_id}{" "}
          <span className="font-normal text-muted-foreground">
            · {KIND_LABELS[proposal.kind]}
          </span>
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Based on {proposal.evidence.count} confirmed{" "}
          {proposal.evidence.count === 1 ? "override" : "overrides"} of this
          rule.
        </p>

        <h3 className="mt-3 text-sm font-medium">Suggested change</h3>
        <div className="mt-1 rounded-md border bg-muted/30 p-3 text-sm">
          <TrackedChanges
            before={proposal.current}
            after={proposal.suggested}
          />
        </div>

        <p className="mt-3 text-sm">
          {gate ? (
            <>
              <span className="font-medium">
                Eval gate: {gate.passed ? "passed" : "failed"}
              </span>{" "}
              <span className="text-muted-foreground">
                (precision {percent(gate.precision)}, recall{" "}
                {percent(gate.recall)} on the labelled set)
              </span>
            </>
          ) : (
            <span className="text-muted-foreground">
              Not run through the eval gate.
            </span>
          )}
        </p>

        <div className="mt-3 flex gap-2">
          <Button
            type="button"
            size="sm"
            disabled={busy}
            onClick={() => onDecide("approved")}
          >
            Approve
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onDecide("rejected")}
          >
            Reject
          </Button>
        </div>
      </article>
    </li>
  );
}

export function ProposalsScreen() {
  const loaded = useLoaded(getProposals);
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<React.ReactNode>(null);

  const list = proposals ?? loaded.data;

  async function act(
    work: () => Promise<Proposal[]>,
    done: (next: Proposal[]) => React.ReactNode,
  ) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await work();
      setProposals(next);
      setNotice(done(next));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl">
      <ScreenHeader
        title="Proposals"
        summary="Rule changes the governance agent suggests from confirmed overrides. Only proposals that pass the eval gate reach you, and approving one only drafts the change."
      />
      <div className="mt-4">
        <Button
          type="button"
          disabled={busy}
          onClick={() =>
            act(runGovernance, (next) =>
              next.length === 0
                ? "The agent found nothing to propose."
                : `${next.length} ${next.length === 1 ? "proposal is" : "proposals are"} waiting.`,
            )
          }
        >
          {busy ? "Working…" : "Run the governance agent"}
        </Button>
      </div>

      <ErrorNotice message={error ?? loaded.error} />
      {notice && <SavedNotice>{notice}</SavedNotice>}

      {list && list.length === 0 && (
        <p className="mt-6 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No proposals are waiting.
        </p>
      )}
      <ul className="mt-4 flex flex-col gap-3">
        {(list ?? []).map((proposal) => (
          <ProposalCard
            key={proposal.id}
            proposal={proposal}
            busy={busy}
            onDecide={(status) =>
              act(
                () => decideProposal(proposal.id, status),
                () =>
                  status === "approved" ? (
                    <>
                      Approved. The change to {proposal.rule_id} is now a draft.{" "}
                      <Link className="underline" href="/brand/rulebook">
                        Approve it in the rulebook
                      </Link>{" "}
                      to put it in force.
                    </>
                  ) : (
                    `Rejected the proposal for ${proposal.rule_id}.`
                  ),
              )
            }
          />
        ))}
      </ul>
    </div>
  );
}
