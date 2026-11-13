"use client";

import { useEffect, useState } from "react";

import { CommentThread } from "@/components/comment-thread";
import { DecisionActions } from "@/components/decision-actions";
import { FixPanel } from "@/components/fix-panel";
import { SEVERITY_EDGE, SeverityBadge } from "@/components/severity-badge";
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
  sourceLabel,
  STATUS_LABELS,
} from "@/lib/findingLabels";
import type { Comment, CommentInput } from "@/lib/reviewDesk";
import { cn } from "@/lib/utils";
import type { DecisionInput, FindingStanding } from "@/lib/workflow";

const SETTLED = ["fix_accepted", "override_confirmed", "resolved"];

function readableDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

// Only inputs a person can read. Anything else in the manifest stays out.
const MANIFEST_LABELS: Record<string, string> = {
  rule: "Rule",
  rule_id: "Rule",
  rule_version: "Rule version",
  rulebook_version: "Rulebook version",
  facts: "Facts",
  fact_ids: "Facts",
  model: "Model",
  models: "Models",
  prompt_version: "Prompt",
  policy_version: "Policy",
  channel: "Channel",
  as_of: "Checked as of",
};

function inputLabel(value: unknown): string {
  if (Array.isArray(value)) return value.map(inputLabel).join(", ");
  if (typeof value === "object" && value !== null) {
    const { id, version } = value as { id?: string; version?: number };
    return version ? `${id}, version ${version}` : String(id ?? "");
  }
  return value === null || value === undefined ? "" : String(value);
}

function Swatch({ colour, label }: { colour: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        aria-hidden="true"
        className="inline-block size-4 rounded-sm border"
        style={{ backgroundColor: colour }}
      />
      {label} {colour}
    </span>
  );
}

/** The failing pair, its ratio and the palette colour that passes. */
function ContrastPreview({ finding }: { finding: Finding }) {
  const step = finding.trace.steps.find(
    (item) => item.tool === "contrast_preview",
  );
  const pair = step?.input_summary.match(/^(#\w{6}) on (#\w{6})$/);
  if (!step || !pair) return null;
  const [result, suggestion] = step.output_summary.split(", try ");

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <Swatch colour={pair[1]} label="Text" />
      <Swatch colour={pair[2]} label="Background" />
      <span>{result}</span>
      {suggestion && <Swatch colour={suggestion} label="Try" />}
    </div>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
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
              {precedent.reviewer}, {readableDate(precedent.date)}
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

  const inputs = Object.entries(result?.manifest ?? {})
    .filter(([key]) => key in MANIFEST_LABELS)
    .map(([key, value]) => [key, inputLabel(value)])
    .filter(([, value]) => value !== "");

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
                  {MANIFEST_LABELS[key]}
                </dt>
                <dd>{value}</dd>
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
  comments,
  versionId,
  onSelect,
  onDecide,
  onComment,
}: {
  contentId: string;
  finding: Finding;
  selected: boolean;
  clauseRefs: ReadonlyMap<string, string>;
  standing: FindingStanding | undefined;
  comments: readonly Comment[];
  versionId: string;
  onSelect: (findingId: string) => void;
  onDecide: (findingId: string, input: DecisionInput) => Promise<void>;
  onComment: (input: CommentInput) => Promise<void>;
}) {
  const confidence = confidenceLabel(finding);
  const source = sourceLabel(finding, clauseRefs);
  const allowed = standing?.allowed ?? [];
  const outcome = standing ? STATUS_LABELS[standing.status] : null;
  const decideThis = (input: DecisionInput) => onDecide(finding.id, input);
  const onThisFinding = comments.filter(
    (comment) => comment.finding_id === finding.id,
  );

  return (
    <article
      id={`finding-${finding.id}`}
      className={cn(
        "flex flex-col gap-3 scroll-mt-20 rounded-xl border border-l-4 bg-card p-4 text-sm shadow-sm transition-shadow",
        SEVERITY_EDGE[finding.severity],
        selected ? "shadow-md ring-2 ring-ring" : "hover:shadow-md",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={finding.severity} />
        <span className="font-medium">{CHECK_LABELS[finding.check]}</span>
        {finding.verdict === "UNSURE" && (
          <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-semibold text-violet-900">
            Needs a reviewer: the AI was unsure
          </span>
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
        title="Show this in the draft"
        className="cursor-pointer rounded-sm text-left text-[0.95rem] leading-relaxed focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        {finding.explanation}
      </button>

      {isDocumentLevel(finding) && (
        <p className="text-muted-foreground">Applies to the whole document.</p>
      )}

      <ContrastPreview finding={finding} />

      <figure className="rounded-lg bg-muted/60 px-3 py-2">
        <figcaption className="text-xs font-medium text-muted-foreground">
          {finding.rule_id ? "Rule it breaks" : "Approved fact"}
          {source && <span className="font-normal"> · {source}</span>}
        </figcaption>
        <blockquote className="mt-1">{finding.cited_text}</blockquote>
      </figure>

      <Precedents findingId={finding.id} />

      <div className="flex flex-wrap items-center gap-2 border-t pt-3">
        {outcome && (
          <p
            className={cn(
              "w-full font-medium",
              SETTLED.includes(standing?.status ?? "open")
                ? "text-emerald-800"
                : "text-amber-900",
            )}
          >
            {SETTLED.includes(standing?.status ?? "open") ? "✓ " : "… "}
            {outcome}
          </p>
        )}
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

      <details>
        <summary className="cursor-pointer font-medium">
          Comments ({onThisFinding.length})
        </summary>
        <div className="mt-2">
          <CommentThread
            label="Comment on this finding"
            comments={onThisFinding}
            versionId={versionId}
            findingId={finding.id}
            onPost={onComment}
          />
        </div>
      </details>
    </article>
  );
}
