"use client";

import { useEffect, useState } from "react";

import { DecisionActions } from "@/components/decision-actions";
import { FixPanel } from "@/components/fix-panel";
import { SEVERITY_MARK } from "@/components/review-document";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import type { Finding, Precedent } from "@/lib/contracts";
import {
  getPrecedents,
  replayVerdict,
  type ReplayResult,
} from "@/lib/engineClient";
import {
  CHECK_LABELS,
  confidenceLabel,
  isDocumentLevel,
  modelLabel,
  SEVERITY_LABELS,
  sourceLabel,
  STATUS_LABELS,
} from "@/lib/findingLabels";
import { cn } from "@/lib/utils";
import type { DecisionInput, FindingStanding } from "@/lib/workflow";

const MANIFEST_LABELS: Record<string, string> = {
  rule_id: "Rule",
  rule_version: "Rule version",
  fact_ids: "Facts",
  models: "Models",
  as_of: "Checked as of",
};

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-sm border px-1.5 text-xs text-muted-foreground">
      {children}
    </span>
  );
}

function Trace({ finding }: { finding: Finding }) {
  const { steps, sources } = finding.trace;
  return (
    <details>
      <summary className="cursor-pointer font-medium">
        Why was this flagged?
      </summary>
      <ol className="mt-2 flex flex-col gap-2">
        {steps.map((step, index) => (
          <li key={index}>
            <code className="text-xs">{step.tool}</code>
            <p className="text-muted-foreground">{step.input_summary}</p>
            <p>{step.output_summary}</p>
          </li>
        ))}
      </ol>
      {finding.vote && (
        <p className="mt-2">
          {finding.vote.agree} of {finding.vote.variants} rubrics agreed
          {finding.vote.split ? ", so the vote was split" : ""}.
        </p>
      )}
      {sources.length > 0 && (
        <p className="mt-2 text-muted-foreground">
          Sources: {sources.join(", ")}
        </p>
      )}
    </details>
  );
}

/** Precedents are context only, so a failed lookup shows nothing rather than an error. */
function Precedents({ findingId }: { findingId: string }) {
  const [precedents, setPrecedents] = useState<Precedent[]>([]);

  useEffect(() => {
    let current = true;
    getPrecedents(findingId).then(
      (loaded) => {
        if (current) setPrecedents(loaded);
      },
      () => {},
    );
    return () => {
      current = false;
    };
  }, [findingId]);

  if (precedents.length === 0) return null;

  return (
    <div>
      <p className="font-medium">Earlier decision, context only</p>
      <ul className="mt-1 flex flex-col gap-1">
        {precedents.map((precedent) => (
          <li key={precedent.decision_id}>
            {precedent.reason}{" "}
            <span className="text-muted-foreground">
              {precedent.reviewer}, {precedent.date}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Replay({ findingId }: { findingId: string }) {
  const [result, setResult] = useState<ReplayResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function replay() {
    setLoading(true);
    setError(null);
    setResult(null);
    replayVerdict(findingId)
      .then(setResult, (caught: ApiError) => setError(caught.message))
      .finally(() => setLoading(false));
  }

  const inputs = Object.entries(result?.manifest ?? {}).filter(
    ([, value]) => value !== null && String(value) !== "",
  );

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={loading}
        onClick={replay}
      >
        Replay
      </Button>
      {error && (
        <p role="alert" className="w-full border-l-2 border-destructive pl-2">
          {error}
        </p>
      )}
      {result && (
        <div className="w-full">
          <p role="status" className="font-medium">
            {result.identical
              ? "Identical result ✓"
              : `Different result: ${result.verdict}`}
          </p>
          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3">
            {inputs.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-muted-foreground">
                  {MANIFEST_LABELS[key] ?? key}
                </dt>
                <dd>{Array.isArray(value) ? value.join(", ") : String(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </>
  );
}

export function FindingCard({
  contentId,
  finding,
  selected,
  clauseRefs,
  standing,
  onSelect,
  onDecide,
}: {
  contentId: string;
  finding: Finding;
  selected: boolean;
  clauseRefs: ReadonlyMap<string, string>;
  standing: FindingStanding | undefined;
  onSelect: (findingId: string) => void;
  onDecide: (findingId: string, input: DecisionInput) => Promise<void>;
}) {
  const confidence = confidenceLabel(finding);
  const source = sourceLabel(finding, clauseRefs);
  const allowed = standing?.allowed ?? [];
  const outcome = standing ? STATUS_LABELS[standing.status] : null;
  const decideThis = (input: DecisionInput) => onDecide(finding.id, input);

  return (
    <article
      className={cn(
        "flex flex-col gap-2 rounded-lg border p-3 text-sm",
        selected && "border-ring bg-accent",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "rounded-sm px-1.5 font-medium text-foreground underline decoration-2 underline-offset-2",
            SEVERITY_MARK[finding.severity],
          )}
        >
          {SEVERITY_LABELS[finding.severity]}
        </span>
        <span className="text-muted-foreground">
          {CHECK_LABELS[finding.check]}
        </span>
        {finding.verdict === "UNSURE" && (
          <span className="font-medium">Needs a reviewer</span>
        )}
        {confidence && <Tag>{confidence}</Tag>}
        <Tag>
          {finding.ai_generated ? `AI: ${modelLabel(finding)}` : "Code check"}
        </Tag>
      </div>

      <button
        type="button"
        aria-pressed={selected}
        onClick={() => onSelect(finding.id)}
        className="cursor-pointer rounded-sm text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        {finding.explanation}
      </button>

      {isDocumentLevel(finding) && (
        <p className="text-muted-foreground">Applies to the whole document.</p>
      )}

      <figure className="border-l-2 pl-3">
        <blockquote>{finding.cited_text}</blockquote>
        {source && (
          <figcaption className="mt-1 text-xs text-muted-foreground">
            {source}
          </figcaption>
        )}
      </figure>

      <Precedents findingId={finding.id} />

      <div className="flex flex-wrap items-center gap-2">
        {outcome && <p className="w-full font-medium">{outcome}</p>}
        {standing?.fix_text && (
          <p className="w-full">Wording: {standing.fix_text}</p>
        )}
        {allowed.includes("accept_fix") && finding.fix_available && (
          <FixPanel
            contentId={contentId}
            finding={finding}
            onDecide={decideThis}
          />
        )}
        <DecisionActions
          allowed={allowed}
          status={standing?.status ?? "open"}
          onDecide={decideThis}
        />
        <Replay findingId={finding.id} />
      </div>

      <Trace finding={finding} />
    </article>
  );
}
