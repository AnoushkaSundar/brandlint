"use client";

import { useEffect, useState } from "react";

import { type CIInsights, getCIInsights } from "@/lib/ci";
import { CI_ENABLED } from "@/lib/navigation";

// How the CI integration is doing, in counts: no drafts, no people. Shows nothing when the
// integration is off or has no data to read.
export function CIInsightsCard() {
  const [data, setData] = useState<CIInsights | null>(null);

  useEffect(() => {
    if (!CI_ENABLED) return;
    let current = true;
    getCIInsights().then(
      (loaded) => {
        if (current) setData(loaded);
      },
      () => {},
    );
    return () => {
      current = false;
    };
  }, []);

  if (!data) return null;
  const { by_result: results } = data;
  return (
    <section aria-labelledby="ci-insights" className="mt-8 rounded-xl border bg-background p-5">
      <h2 id="ci-insights" className="text-lg font-semibold">
        CI runs
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {data.runs_7d} in the last 7 days, {data.runs_30d} in 30. {results.pass} passed, {results.fail} failed,{" "}
        {results.error} couldn&apos;t be checked.
        {data.average_seconds !== null && ` A run takes ${data.average_seconds} seconds on average.`}
      </p>
      {data.failure_reasons.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-sm">
          {data.failure_reasons.map((item) => (
            <li key={item.reason}>
              {item.reason} ({item.count})
            </li>
          ))}
        </ul>
      )}
      {data.tokens.length > 0 && (
        <table className="mt-4 w-full text-left text-sm">
          <caption className="sr-only">Service token use</caption>
          <thead>
            <tr>
              <th scope="col" className="py-1 font-medium">Token</th>
              <th scope="col" className="py-1 font-medium">Runs in 7 days</th>
              <th scope="col" className="py-1 font-medium">Last used</th>
            </tr>
          </thead>
          <tbody>
            {data.tokens.map((token) => (
              <tr key={token.prefix + token.name}>
                <td className="py-1">
                  {token.name} <code>{token.prefix}</code>
                  {token.revoked && " (revoked)"}
                </td>
                <td className="py-1">{token.runs_7d}</td>
                <td className="py-1">
                  {token.last_used_at ? new Date(token.last_used_at).toLocaleString() : "Never"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
