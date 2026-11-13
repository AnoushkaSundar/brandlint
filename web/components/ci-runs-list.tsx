"use client";

import Link from "next/link";

import { ErrorNotice, ScreenHeader, useLoaded } from "@/components/brand-ui";
import { getCIRuns, RESULT_LABELS, STATE_LABELS } from "@/lib/ci";

export function CIRunsList() {
  const { data, error } = useLoaded(getCIRuns);

  return (
    <div className="mx-auto w-full max-w-5xl">
      <ScreenHeader
        title="CI runs"
        summary="Each time a pull request changed copy, BrandLint checked it. Open a run to see what it found."
      />
      <ErrorNotice message={error} />
      {!data && !error && (
        <p role="status" className="mt-4 text-sm text-muted-foreground">
          Loading…
        </p>
      )}
      {data?.length === 0 && (
        <p className="mt-6 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No runs yet. Once your repo&apos;s workflow runs, its checks show up here.
        </p>
      )}
      {data && data.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-lg border">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">CI runs</caption>
            <thead className="border-b bg-muted">
              <tr>
                <th scope="col" className="p-3 font-medium">Repo</th>
                <th scope="col" className="p-3 font-medium">Pull request</th>
                <th scope="col" className="p-3 font-medium">Result</th>
                <th scope="col" className="p-3 font-medium">Files</th>
                <th scope="col" className="p-3 font-medium">When</th>
                <th scope="col" className="p-3 font-medium"><span className="sr-only">Open</span></th>
              </tr>
            </thead>
            <tbody>
              {data.map((run) => (
                <tr key={run.id} className="border-b last:border-b-0">
                  <td className="p-3 break-all">{run.repo}</td>
                  <td className="p-3">{run.pr ? `#${run.pr}` : "—"}</td>
                  <td className="p-3">
                    {run.result ? RESULT_LABELS[run.result] : STATE_LABELS[run.state]}
                  </td>
                  <td className="p-3">{run.files}</td>
                  <td className="p-3">{new Date(run.created_at).toLocaleString()}</td>
                  <td className="p-3">
                    <Link
                      href={`/ci/runs/${run.id}`}
                      className="underline underline-offset-2"
                      aria-label={`Open the run for ${run.repo}${run.pr ? ` pull request ${run.pr}` : ""}`}
                    >
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
