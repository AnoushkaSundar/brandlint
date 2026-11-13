"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ErrorNotice, ScreenHeader } from "@/components/brand-ui";
import { SeverityBadge } from "@/components/severity-badge";
import { ApiError } from "@/lib/api";
import { getCIRun, RESULT_LABELS, STATE_LABELS } from "@/lib/ci";
import type { CIFinding, CIRunStatus } from "@/lib/contracts";
import { STATUS_LABELS } from "@/lib/findingLabels";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;

function Banner({ run }: { run: CIRunStatus }) {
  const failed = run.result === "fail";
  const passed = run.result === "pass";
  const text = passed
    ? `${RESULT_LABELS.pass}: no finding blocks this run.`
    : failed
      ? `${RESULT_LABELS.fail}: ${run.reasons[0] ?? "a finding blocks this run."}`
      : run.state === "error"
        ? (run.reasons[0] ?? STATE_LABELS.error)
        : "Checking the copy. This page updates by itself.";
  return (
    <div
      role="status"
      className={cn(
        "mt-6 rounded-xl border p-4 text-base font-semibold",
        passed && "border-green-700 bg-green-50 text-green-900",
        failed && "border-red-700 bg-red-50 text-red-900",
        !passed && !failed && "bg-muted",
      )}
    >
      {text}
      {passed && (
        <p className="mt-1 text-sm font-normal">
          A pass means no finding blocks the run. It isn&apos;t an approval.
        </p>
      )}
    </div>
  );
}

function FindingRow({ finding, path, contentId }: { finding: CIFinding; path: string; contentId: string }) {
  const where = finding.line ? `${path}:${finding.line}` : path;
  return (
    <li
      id={`finding-${finding.id}`}
      className="scroll-mt-20 rounded-lg border p-3 text-sm target:ring-2 target:ring-ring"
    >
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={finding.severity} />
        {finding.verdict === "UNSURE" && (
          <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-semibold text-violet-900">
            Needs a reviewer
          </span>
        )}
        <span className="font-medium">{finding.title}</span>
        {finding.blocking ? (
          <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-900">
            Blocks the run
          </span>
        ) : (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-semibold">
            Doesn&apos;t block
          </span>
        )}
      </div>
      <p className="mt-2 text-muted-foreground">
        {finding.rule_id ? `Rule ${finding.rule_id}` : "No rule"} · {where} ·{" "}
        {STATUS_LABELS[finding.status] ?? "Open"}
      </p>
      {finding.span && (
        <blockquote className="mt-2 border-l-2 pl-3 text-muted-foreground">
          {finding.span}
        </blockquote>
      )}
      <p className="mt-2">
        <Link
          href={`/content/${contentId}/review?finding=${encodeURIComponent(finding.id)}`}
          className="underline underline-offset-2"
        >
          Open this finding in the review screen
        </Link>
      </p>
    </li>
  );
}

export function CIRunScreen({ id }: { id: string }) {
  const [run, setRun] = useState<CIRunStatus | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let current = true;
    let timer: number | undefined;
    const load = () =>
      getCIRun(id).then(
        (loaded) => {
          if (!current) return;
          setRun(loaded);
          setError(null);
          if (loaded.state === "running" || loaded.state === "queued") {
            timer = window.setTimeout(load, POLL_MS);
          }
        },
        (caught: ApiError) => {
          if (current) setError(caught);
        },
      );
    load();
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [id]);

  // A link to #finding-… arrives before the findings do, so scroll once they are here.
  useEffect(() => {
    if (!run || !window.location.hash.startsWith("#finding-")) return;
    document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [run]);

  if (error?.status === 404) {
    return (
      <div className="mx-auto w-full max-w-4xl">
        <ScreenHeader title="Run not found" summary="There's no CI run with that link in your workspace." />
        <p className="mt-4 text-sm">
          <Link href="/ci/runs" className="underline underline-offset-2">
            See your workspace&apos;s CI runs
          </Link>
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl">
      <ScreenHeader
        title="CI run"
        summary="What BrandLint found in the copy a pull request changed. Open a finding to decide on it."
      />
      <ErrorNotice message={error?.message ?? null} />
      {!run && !error && (
        <p role="status" className="mt-4 text-sm text-muted-foreground">
          Loading…
        </p>
      )}
      {run && (
        <>
          <Banner run={run} />
          {run.reasons.length > 1 && run.result === "fail" && (
            <ul className="mt-3 list-disc pl-5 text-sm text-muted-foreground">
              {run.reasons.slice(1).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-sm text-muted-foreground">
            Fails on {run.policy.severity_threshold} and above
            {run.policy.fail_on_unsure ? ", and on anything the AI was unsure about" : ""}. An
            admin changes this in CI settings.
          </p>
          <ul className="mt-6 flex flex-col gap-6">
            {run.files.map((file) => (
              <li key={file.path}>
                <h2 className="text-lg font-semibold break-all">{file.path}</h2>
                <p className="text-sm text-muted-foreground">
                  {STATE_LABELS[file.state]}
                  {file.state === "done" && file.findings.length === 0 && " · no findings"}
                </p>
                {file.findings.length > 0 && (
                  <ul className="mt-3 flex flex-col gap-3">
                    {file.findings.map((finding) => (
                      <FindingRow
                        key={finding.id}
                        finding={finding}
                        path={file.path}
                        contentId={file.content_id}
                      />
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
