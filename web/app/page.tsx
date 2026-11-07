import {
  ArrowRight,
  BookOpen,
  Check,
  EyeOff,
  FileSearch,
  Lock,
  RotateCcw,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { DEMO_ACCOUNTS, DEMO_MODE } from "@/lib/demo";
import { HOME_HREF } from "@/lib/navigation";

export const metadata: Metadata = {
  title: "BrandLint: brand checks before anything is published",
};

const STEPS = [
  {
    icon: BookOpen,
    title: "Guidelines become a rulebook",
    body: "Upload the brand guideline. BrandLint drafts one rule per clause and flags rules that contradict each other. An admin approves the rulebook. AI never does.",
  },
  {
    icon: FileSearch,
    title: "Every draft is checked",
    body: "Text, Word, PDF, web pages and images are checked for tone, terminology, unsupported claims, outdated facts, visual misuse and accessibility.",
  },
  {
    icon: Check,
    title: "Each finding shows its source",
    body: "A finding quotes the rule or approved fact it breaks, and offers a minimal fix that keeps the writer's meaning. Anything without a source is never shown.",
  },
  {
    icon: Users,
    title: "People decide",
    body: "Creators fix or explain, reviewers confirm, managers approve, and legal signs off risky claims. Serious findings can only be overridden by a reviewer.",
  },
];

const TRUST = [
  {
    icon: RotateCcw,
    title: "Same input, same verdict",
    body: "Pass or fail comes from code, or from an AI check at temperature 0 on a pinned model. Replay re-runs any verdict to prove it.",
  },
  {
    icon: Lock,
    title: "Secrets never reach a model",
    body: "Unreleased product names and personal data are swapped for tokens like [PRODUCT_1] before any AI sees the text. Restricted content never leaves the server.",
  },
  {
    icon: EyeOff,
    title: "Hidden instructions are caught",
    body: "White-on-white text telling an AI reviewer to approve the piece is flagged as critical, and the creator can't override it.",
  },
  {
    icon: ShieldCheck,
    title: "Rules improve, with permission",
    body: "When reviewers keep overriding a rule, BrandLint drafts a clearer version. It has to pass a regression test, then an admin approves it.",
  },
];

const RESULTS = [
  { value: "10 of 10", label: "planted issues found" },
  { value: "0 of 7", label: "injection attacks got through" },
  { value: "< 0.2 s", label: "to the first finding" },
  { value: "Identical", label: "verdicts on Replay" },
];

function SampleFinding() {
  return (
    <figure
      aria-label="An example finding"
      className="rounded-xl border bg-background p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-full bg-destructive/10 px-2 py-0.5 font-medium text-destructive">
          High
        </span>
        <span className="rounded-full bg-muted px-2 py-0.5">Claim</span>
        <span className="text-muted-foreground">Rule R-CLAIM-01 · §4.1</span>
      </div>
      <p className="mt-3 text-sm">
        &ldquo;Companies that move to Tarnhollow cut onboarding time by{" "}
        <mark className="rounded bg-yellow-200 px-0.5 text-foreground">80%</mark>
        .&rdquo;
      </p>
      <blockquote className="mt-3 border-l-2 pl-3 text-sm text-muted-foreground">
        Approved fact: Customers cut onboarding time by 38% on average.
      </blockquote>
      <div className="mt-4 rounded-lg bg-muted p-3 text-sm">
        <p className="font-medium">Suggested fix</p>
        <p className="mt-1">
          <del className="text-muted-foreground">by 80%</del>{" "}
          <ins className="font-medium no-underline">by 38%</ins>
        </p>
      </div>
      <figcaption className="mt-3 text-xs text-muted-foreground">
        The claim was split across two paragraphs. BrandLint read them together.
      </figcaption>
    </figure>
  );
}

export default function Home() {
  if (!DEMO_MODE) redirect(HOME_HREF);

  return (
    <div className="flex-1 bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <span className="flex items-center gap-2 font-semibold">
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Check aria-hidden="true" className="size-4" strokeWidth={3} />
            </span>
            BrandLint
          </span>
          <Link
            href="/login"
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            Try the demo
          </Link>
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl gap-12 px-6 py-16 md:grid-cols-2 md:items-center md:py-24">
          <div>
            <p className="text-sm font-medium text-primary">
              Brand governance before publishing
            </p>
            <h1 className="mt-3 text-4xl font-semibold tracking-tight md:text-5xl">
              Catch off-brand content before anyone sees it.
            </h1>
            <p className="mt-5 text-lg text-muted-foreground">
              BrandLint checks every draft against your approved rulebook and
              facts. Every problem cites the rule it breaks, and a person makes
              every decision.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/login"
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3 font-medium text-primary-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                Start the demo
                <ArrowRight aria-hidden="true" className="size-4" />
              </Link>
              <a
                href="#how-it-works"
                className="inline-flex items-center rounded-lg border px-5 py-3 font-medium focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                How it works
              </a>
            </div>
            <p className="mt-4 text-sm text-muted-foreground">
              No sign-up. A guided tour shows you what to click and why, as
              each person in the workflow.
            </p>
          </div>
          <SampleFinding />
        </section>

        <section className="border-y bg-muted/40">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <h2 className="text-2xl font-semibold tracking-tight">The problem</h2>
            <p className="mt-3 max-w-3xl text-muted-foreground">
              Agencies, in-house teams and AI tools now produce content faster
              than anyone can check it. The guidelines live in a PDF, the
              approved facts in a spreadsheet, and the reviewer has minutes.
              Outdated statistics, banned superlatives, leaked product codenames
              and even hidden instructions aimed at AI reviewers get published.
            </p>
          </div>
        </section>

        <section id="how-it-works" className="mx-auto max-w-6xl px-6 py-16">
          <h2 className="text-2xl font-semibold tracking-tight">How it works</h2>
          <ol className="mt-8 grid gap-6 md:grid-cols-4">
            {STEPS.map((step, index) => (
              <li key={step.title} className="rounded-xl border p-5">
                <step.icon aria-hidden="true" className="size-5 text-primary" />
                <p className="mt-3 text-xs font-medium text-muted-foreground">
                  Step {index + 1}
                </p>
                <h3 className="mt-1 font-medium">{step.title}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="border-y bg-muted/40">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <h2 className="text-2xl font-semibold tracking-tight">
              Built so you can trust it
            </h2>
            <ul className="mt-8 grid gap-6 md:grid-cols-2">
              {TRUST.map((item) => (
                <li key={item.title} className="flex gap-4">
                  <item.icon
                    aria-hidden="true"
                    className="mt-0.5 size-5 shrink-0 text-primary"
                  />
                  <div>
                    <h3 className="font-medium">{item.title}</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {item.body}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-6 py-16">
          <h2 className="text-2xl font-semibold tracking-tight">
            Results on our demo set
          </h2>
          <dl className="mt-8 grid grid-cols-2 gap-6 md:grid-cols-4">
            {RESULTS.map((result) => (
              <div key={result.label} className="rounded-xl border p-5">
                <dt className="text-sm text-muted-foreground">{result.label}</dt>
                <dd className="mt-1 text-2xl font-semibold">{result.value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 text-sm text-muted-foreground">
            Measured with the real models on our three demo pieces and seven
            injected attack pieces. A small set, not a benchmark.
          </p>
        </section>

        <section className="border-t bg-muted/40">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <h2 className="text-2xl font-semibold tracking-tight">
              Five roles, one workflow
            </h2>
            <ul className="mt-8 grid gap-4 md:grid-cols-5">
              {DEMO_ACCOUNTS.map((account) => (
                <li key={account.role} className="rounded-xl border bg-background p-4">
                  <h3 className="font-medium">{account.label}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {account.does}
                  </p>
                </li>
              ))}
            </ul>
            <Link
              href="/login"
              className="mt-10 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3 font-medium text-primary-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              Try the demo
              <ArrowRight aria-hidden="true" className="size-4" />
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto max-w-6xl px-6 py-6 text-sm text-muted-foreground">
          BrandLint, by team anoushkasundar: Alapan Sen and Anoushka Sundar.
          Tarnhollow is a fictional brand made for this demo.
        </div>
      </footer>
    </div>
  );
}
