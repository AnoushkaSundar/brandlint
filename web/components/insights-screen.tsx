"use client";

import { TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";

import {
  ErrorNotice,
  ScreenHeader,
  SELECT_STYLE,
  useLoaded,
} from "@/components/brand-ui";
import { CIInsightsCard } from "@/components/ci-insights";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CHANNELS } from "@/lib/content";
import { getSignals, getSpotChecks, percent } from "@/lib/insights";

const CELL = "px-3 py-2";

/** One series, so no legend: the section title names it, and every bar has its value. */
function Bars({
  label,
  rows,
}: {
  label: string;
  rows: { key: string; value: number; text: string }[];
}) {
  const largest = Math.max(1, ...rows.map((row) => row.value));
  return (
    <ul aria-label={label} className="mt-3 flex flex-col gap-1.5">
      {rows.map((row) => (
        <li
          key={row.key}
          className="grid grid-cols-[7rem_1fr_3.5rem] items-center gap-2 text-sm"
        >
          <span className="truncate">{row.key}</span>
          <span className="h-3 rounded-sm bg-muted" aria-hidden="true">
            <span
              className="block h-3 rounded-sm bg-primary"
              style={{ width: `${(row.value / largest) * 100}%` }}
            />
          </span>
          <span className="text-right tabular-nums">{row.text}</span>
        </li>
      ))}
    </ul>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="rounded-lg border p-4">
      <h2 id={id} className="font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="mt-3 text-sm text-muted-foreground">{children}</p>;
}

export function InsightsScreen() {
  const [channel, setChannel] = useState("");
  const [source, setSource] = useState("");
  const load = useCallback(
    () => getSignals({ channel, source: source.trim() }),
    [channel, source],
  );
  const { data, error } = useLoaded(load);
  const spotChecks = useLoaded(getSpotChecks);

  const overrides = Object.entries(data?.override_rate_by_rule ?? {}).sort(
    ([, a], [, b]) => b.rate - a.rate || b.findings - a.findings,
  );
  const splits = Object.entries(data?.vote_split_by_rule ?? {});

  return (
    <div className="mx-auto w-full max-w-5xl">
      <ScreenHeader
        title="Insights"
        summary="Where the rules work and where they may need attention, from each piece's latest review."
      />

      <div className="mt-4 flex flex-wrap gap-4">
        <div className="flex flex-col gap-1">
          <Label htmlFor="insights-channel">Channel</Label>
          <select
            id="insights-channel"
            className={SELECT_STYLE}
            value={channel}
            onChange={(event) => setChannel(event.target.value)}
          >
            <option value="">All channels</option>
            {CHANNELS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="insights-source">Team or agency</Label>
          <Input
            id="insights-source"
            className="w-56"
            placeholder="All sources"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          />
        </div>
      </div>

      <ErrorNotice message={error} />
      {!data && !error && (
        <p role="status" className="mt-4 text-sm text-muted-foreground">
          Loading…
        </p>
      )}

      {data && (
        <>
          <p className="mt-4 text-sm text-muted-foreground">
            {data.reviewed} of {data.pieces} pieces reviewed.
            {data.unavailable.length > 0 &&
              ` ${data.unavailable.length} couldn't be read and aren't counted.`}
          </p>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Section id="top-rules" title="Most broken rules">
              {data.top_rules.length ? (
                <Bars
                  label="Findings per rule"
                  rows={data.top_rules.slice(0, 8).map((rule) => ({
                    key: rule.rule_id,
                    value: rule.findings,
                    text: String(rule.findings),
                  }))}
                />
              ) : (
                <Empty>No findings yet.</Empty>
              )}
            </Section>

            <Section id="by-day" title="Findings over time">
              {data.findings_by_day.length ? (
                <Bars
                  label="Findings per day"
                  rows={data.findings_by_day.map((day) => ({
                    key: day.day,
                    value: day.findings,
                    text: String(day.findings),
                  }))}
                />
              ) : (
                <Empty>No findings yet.</Empty>
              )}
            </Section>
          </div>

          <div className="mt-4">
            <Section id="override-rates" title="Override rate per rule">
              <p className="mt-1 text-sm text-muted-foreground">
                Overrides a reviewer confirmed. Above 30%, a rule may be
                unclear.
              </p>
              {overrides.length ? (
                <div tabIndex={0} className="mt-3 overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">
                      Override rate per rule
                    </caption>
                    <thead className="border-b">
                      <tr>
                        <th scope="col" className={CELL}>
                          Rule
                        </th>
                        <th scope="col" className={CELL}>
                          Findings
                        </th>
                        <th scope="col" className={CELL}>
                          Overridden
                        </th>
                        <th scope="col" className={CELL}>
                          Rate
                        </th>
                        <th scope="col" className={CELL}>
                          Signal
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {overrides.map(([ruleId, rule]) => (
                        <tr key={ruleId} className="border-b last:border-0">
                          <td className={CELL}>{ruleId}</td>
                          <td className={`${CELL} tabular-nums`}>
                            {rule.findings}
                          </td>
                          <td className={`${CELL} tabular-nums`}>
                            {rule.overridden}
                          </td>
                          <td className={`${CELL} tabular-nums`}>
                            {percent(rule.rate)}
                          </td>
                          <td className={CELL}>
                            {rule.may_be_unclear && (
                              <span className="inline-flex items-center gap-1 font-medium">
                                <TriangleAlert
                                  aria-hidden="true"
                                  className="size-4"
                                />
                                May be unclear
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty>No rule has findings yet.</Empty>
              )}
              <p className="mt-3 text-sm">
                <Link className="underline" href="/proposals">
                  Ask the governance agent for rule changes
                </Link>
              </p>
            </Section>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Section id="vote-splits" title="Vote splits per rule">
              <p className="mt-1 text-sm text-muted-foreground">
                How often the model&apos;s repeated runs disagreed.
              </p>
              {splits.length ? (
                <Bars
                  label="Vote split rate per rule"
                  rows={splits.map(([ruleId, split]) => ({
                    key: ruleId,
                    value: split.rate,
                    text: `${percent(split.rate)} of ${split.voted}`,
                  }))}
                />
              ) : (
                <Empty>No voted findings yet.</Empty>
              )}
            </Section>

            <Section id="creator-signals" title="Overrides often rejected">
              <p className="mt-1 text-sm text-muted-foreground">
                Creators who may need guidance on the rules. A signal for
                governance, not a ranking.
              </p>
              {data.creator_signals.length ? (
                <ul className="mt-3 flex flex-col gap-1 text-sm">
                  {data.creator_signals.map((signal) => (
                    <li key={signal.creator}>
                      {signal.creator}: {percent(signal.rejected_rate)} of{" "}
                      {signal.overrides} overrides rejected
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>No signal.</Empty>
              )}
            </Section>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Section id="gaps" title="Guideline gaps">
              <p className="mt-1 text-sm text-muted-foreground">
                Concerns no rule or fact covers. They never reach creators.
              </p>
              {data.gaps.length ? (
                <ul className="mt-3 flex flex-col gap-2 text-sm">
                  {data.gaps.map((gap) => (
                    <li key={gap.id} className="rounded-md border p-2">
                      <span className="font-medium capitalize">
                        {gap.check}
                      </span>
                      : “{gap.text}”
                      <span className="block text-muted-foreground">
                        {gap.explanation}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>No gaps logged.</Empty>
              )}
            </Section>

            <Section id="spot-checks" title="Spot-check sample">
              <p className="mt-1 text-sm text-muted-foreground">
                Passed pieces sampled for a person to check again.
              </p>
              <ErrorNotice message={spotChecks.error} />
              {spotChecks.data?.length ? (
                <ul className="mt-3 flex flex-col gap-1 text-sm">
                  {spotChecks.data.map((item) => (
                    <li key={item.review_id}>
                      <Link
                        className="underline"
                        href={`/content/${item.content_id}`}
                      >
                        {item.content_id}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                spotChecks.data && <Empty>Nothing sampled.</Empty>
              )}
            </Section>
          </div>
        </>
      )}
      <CIInsightsCard />
    </div>
  );
}
