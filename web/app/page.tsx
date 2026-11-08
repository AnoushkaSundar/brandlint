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

import { AnimatedEntry } from "@/components/animated-entry";
import { StatCounter } from "@/components/stat-counter";
import { DEMO_ACCOUNTS, DEMO_MODE } from "@/lib/demo";
import { HOME_HREF } from "@/lib/navigation";

export const metadata: Metadata = {
  title: "BrandLint: brand checks before anything is published",
  description:
    "Pre-publication brand governance: every draft is reviewed against an approved rulebook, and people make every decision.",
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
  { value: "10/10", label: "planted issues found" },
  { value: "0/7", label: "injection attacks got through" },
  { value: "< 0.2s", label: "to the first finding" },
  { value: "100%", label: "identical verdicts on Replay" },
];

function SampleFinding() {
  return (
    <figure
      aria-label="An example finding"
      className="animate-float rounded-2xl border bg-background/95 p-6 shadow-2xl backdrop-blur-sm text-foreground"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-full bg-destructive/15 px-2.5 py-1 font-semibold text-destructive">
          High severity
        </span>
        <span className="rounded-full bg-primary/10 px-2.5 py-1 text-primary font-medium">Claim</span>
        <span className="text-muted-foreground">Rule R-CLAIM-01 · §4.1</span>
      </div>
      <p className="mt-4 text-sm leading-relaxed">
        &ldquo;Companies that move to Tarnhollow cut onboarding time by{" "}
        <mark className="rounded-sm bg-yellow-200 px-0.5 font-medium text-foreground">80%</mark>
        .&rdquo;
      </p>
      <blockquote className="mt-3 border-l-2 border-primary/40 pl-3 text-sm text-muted-foreground italic">
        Approved fact: customers cut onboarding time by 38% on average.
      </blockquote>
      <div className="mt-4 rounded-xl bg-muted/60 p-3.5 text-sm">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Suggested fix</p>
        <p className="mt-1.5">
          <del className="text-muted-foreground">by 80%</del>{" "}
          <ins className="font-semibold text-primary no-underline">by 38%</ins>
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
      {/* ── Sticky header ── */}
      <header className="sticky top-0 z-50 border-b bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <span className="flex items-center gap-2 font-semibold">
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Check aria-hidden="true" className="size-4" strokeWidth={3} />
            </span>
            BrandLint
          </span>
          <Link
            href="/login"
            className="group flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-all hover:opacity-90 hover:shadow-lg hover:shadow-primary/30 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            Try the demo
            <ArrowRight aria-hidden="true" className="size-3.5 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </header>

      <main>
        {/* ── Hero ── */}
        <section className="relative overflow-hidden bg-[#09090f] text-white">
          {/* Background orbs */}
          <div
            aria-hidden="true"
            className="animate-orb-drift pointer-events-none absolute -top-40 -left-40 size-[600px] rounded-full bg-primary opacity-[0.12] blur-3xl"
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-40 top-20 size-[500px] rounded-full opacity-[0.08] blur-3xl"
            style={{ background: "oklch(0.65 0.22 300)", animationDelay: "2s" }}
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute bottom-0 left-1/2 size-[800px] -translate-x-1/2 rounded-full bg-primary opacity-[0.05] blur-3xl"
          />

          {/* Subtle grid */}
          <div aria-hidden="true" className="hero-grid pointer-events-none absolute inset-0" />

          <div className="relative mx-auto grid max-w-6xl gap-12 px-6 py-24 md:grid-cols-2 md:items-center md:py-36">
            <div>
              <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs font-medium text-white/70 backdrop-blur-sm">
                <span className="size-1.5 animate-pulse rounded-full bg-emerald-400" />
                Brand Governance Platform
              </div>
              <h1 className="text-4xl font-bold tracking-tight md:text-6xl leading-[1.1]">
                Catch{" "}
                <span className="animate-shimmer-text">off-brand content</span>
                <br />
                before anyone sees it.
              </h1>
              <p className="mt-6 text-lg text-white/60 leading-relaxed">
                BrandLint checks every draft against your approved rulebook and facts.
                Every problem cites the rule it breaks, and a person makes every decision.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  href="/login"
                  className="group inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3.5 font-semibold text-white shadow-lg shadow-primary/40 transition-all hover:opacity-90 hover:shadow-primary/60 hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  Start the demo
                  <ArrowRight aria-hidden="true" className="size-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
                <a
                  href="#how-it-works"
                  className="inline-flex items-center rounded-xl border border-white/15 bg-white/5 px-6 py-3.5 font-medium text-white/80 backdrop-blur-sm transition-all hover:bg-white/10 hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  How it works
                </a>
              </div>
              <p className="mt-4 text-sm text-white/40">
                No sign-up needed · Guided tour included · Real AI checks
              </p>
            </div>

            <div className="relative flex justify-center md:justify-end">
              <div className="absolute inset-0 rounded-3xl bg-primary/10 blur-2xl" />
              <div className="relative w-full max-w-sm">
                <SampleFinding />
              </div>
            </div>
          </div>
        </section>

        {/* ── Stats ── */}
        <section className="border-y bg-muted/30">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <AnimatedEntry>
              <p className="mb-10 text-center text-sm font-medium uppercase tracking-widest text-muted-foreground">
                Measured on our demo set — not a benchmark
              </p>
            </AnimatedEntry>
            <div className="grid grid-cols-2 gap-8 md:grid-cols-4">
              {RESULTS.map((r, i) => (
                <AnimatedEntry key={r.label} delay={i * 100}>
                  <StatCounter value={r.value} label={r.label} />
                </AnimatedEntry>
              ))}
            </div>
          </div>
        </section>

        {/* ── Problem ── */}
        <section className="mx-auto max-w-6xl px-6 py-20">
          <AnimatedEntry>
            <div className="rounded-2xl border bg-muted/40 p-8 md:p-12">
              <p className="text-xs font-semibold uppercase tracking-widest text-primary">The problem</p>
              <h2 className="mt-3 text-2xl font-bold tracking-tight md:text-3xl">
                Content moves faster than anyone can check it.
              </h2>
              <p className="mt-4 max-w-3xl text-muted-foreground leading-relaxed">
                Agencies, in-house teams and AI tools now produce content faster than anyone can
                review it. The guidelines live in a PDF, the approved facts in a spreadsheet, and
                the reviewer has minutes. Outdated statistics, banned superlatives, leaked product
                codenames and even hidden instructions aimed at AI reviewers get published.
              </p>
            </div>
          </AnimatedEntry>
        </section>

        {/* ── How it works ── */}
        <section id="how-it-works" className="border-t bg-muted/20">
          <div className="mx-auto max-w-6xl px-6 py-20">
            <AnimatedEntry>
              <p className="text-xs font-semibold uppercase tracking-widest text-primary">How it works</p>
              <h2 className="mt-3 text-2xl font-bold tracking-tight md:text-3xl">Four steps from guideline to verdict</h2>
            </AnimatedEntry>
            <ol className="mt-12 grid gap-6 md:grid-cols-4">
              {STEPS.map((step, index) => (
                <AnimatedEntry key={step.title} delay={index * 120}>
                  <li className="group relative rounded-2xl border bg-background p-6 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-md hover:border-primary/30">
                    <div className="mb-4 flex items-center gap-3">
                      <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-xs font-bold text-primary">
                        {index + 1}
                      </span>
                      <step.icon aria-hidden="true" className="size-4 text-primary" />
                    </div>
                    <h3 className="font-semibold leading-snug">{step.title}</h3>
                    <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{step.body}</p>
                  </li>
                </AnimatedEntry>
              ))}
            </ol>
          </div>
        </section>

        {/* ── Trust ── */}
        <section className="relative overflow-hidden bg-[#09090f] text-white">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute right-0 top-0 size-[600px] rounded-full bg-primary opacity-[0.06] blur-3xl"
          />
          <div className="relative mx-auto max-w-6xl px-6 py-20">
            <AnimatedEntry>
              <p className="text-xs font-semibold uppercase tracking-widest text-primary">Built so you can trust it</p>
              <h2 className="mt-3 text-2xl font-bold tracking-tight text-white md:text-3xl">
                Deterministic. Transparent. Auditable.
              </h2>
            </AnimatedEntry>
            <ul className="mt-12 grid gap-6 md:grid-cols-2">
              {TRUST.map((item, i) => (
                <AnimatedEntry key={item.title} delay={i * 100}>
                  <li className="flex gap-5 rounded-2xl border border-white/8 bg-white/4 p-6 backdrop-blur-sm transition-all duration-300 hover:bg-white/7 hover:border-white/15">
                    <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/20">
                      <item.icon aria-hidden="true" className="size-5 text-primary" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-white">{item.title}</h3>
                      <p className="mt-1.5 text-sm text-white/55 leading-relaxed">{item.body}</p>
                    </div>
                  </li>
                </AnimatedEntry>
              ))}
            </ul>
          </div>
        </section>

        {/* ── Roles ── */}
        <section className="mx-auto max-w-6xl px-6 py-20">
          <AnimatedEntry>
            <p className="text-xs font-semibold uppercase tracking-widest text-primary">Five roles, one workflow</p>
            <h2 className="mt-3 text-2xl font-bold tracking-tight md:text-3xl">
              Everyone has a part to play.
            </h2>
            <p className="mt-3 text-muted-foreground">
              The demo lets you step into each role and see exactly what they can and can&apos;t do.
            </p>
          </AnimatedEntry>
          <ul className="mt-10 grid gap-4 md:grid-cols-5">
            {DEMO_ACCOUNTS.map((account, i) => (
              <AnimatedEntry key={account.role} delay={i * 80}>
                <li className="rounded-2xl border bg-background p-5 transition-all duration-300 hover:-translate-y-1 hover:shadow-md hover:border-primary/30">
                  <div className="mb-3 size-8 rounded-lg bg-primary/10 flex items-center justify-center">
                    <span className="text-xs font-bold text-primary">{account.label[0]}</span>
                  </div>
                  <h3 className="font-semibold">{account.label}</h3>
                  <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">{account.does}</p>
                </li>
              </AnimatedEntry>
            ))}
          </ul>
        </section>

        {/* ── CTA ── */}
        <section className="border-t bg-[#09090f]">
          <AnimatedEntry>
            <div className="mx-auto max-w-2xl px-6 py-24 text-center">
              <h2 className="text-3xl font-bold tracking-tight text-white md:text-4xl">
                Ready to see it in action?
              </h2>
              <p className="mt-4 text-white/55">
                No sign-up. A five-minute guided tour through every role in the workflow.
                Everything you see is real — real AI checks, real permissions.
              </p>
              <Link
                href="/login"
                className="group mt-10 inline-flex items-center gap-2 rounded-xl bg-primary px-8 py-4 text-lg font-semibold text-white shadow-xl shadow-primary/40 transition-all hover:opacity-90 hover:shadow-primary/60 hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                Try BrandLint free
                <ArrowRight aria-hidden="true" className="size-5 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </div>
          </AnimatedEntry>
        </section>
      </main>

      <footer className="border-t bg-[#09090f]">
        <div className="mx-auto max-w-6xl px-6 py-6 text-sm text-white/30">
          BrandLint, by team anoushkasundar: Alapan Sen and Anoushka Sundar.
          Tarnhollow is a fictional brand made for this demo.
        </div>
      </footer>
    </div>
  );
}
