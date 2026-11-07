import { login } from "@/lib/auth";
import type { Role } from "@/lib/contracts";
import { canRoleOpen, HOME_HREF } from "@/lib/navigation";

// The public demo shows a role switcher and a guided tour. Both sign in through the
// ordinary login as a real demo account, so the API still enforces every permission.
// Never turn this on for a real deployment.
export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
export const DEMO_PASSWORD =
  process.env.NEXT_PUBLIC_DEMO_PASSWORD ?? "brandlint-demo";

export type DemoAccount = {
  role: Role;
  email: string;
  label: string;
  does: string;
};

export const DEMO_ACCOUNTS: readonly DemoAccount[] = [
  {
    role: "creator",
    email: "agency@tarnhollow.example",
    label: "Creator",
    does: "Uploads drafts, accepts fixes, and asks to override low or medium findings.",
  },
  {
    role: "reviewer",
    email: "reviewer@tarnhollow.example",
    label: "Reviewer",
    does: "Clears findings the AI was unsure about, and confirms or rejects overrides.",
  },
  {
    role: "manager",
    email: "manager@tarnhollow.example",
    label: "Manager",
    does: "Approves content for publication.",
  },
  {
    role: "legal",
    email: "legal@tarnhollow.example",
    label: "Legal",
    does: "Signs off any piece that makes a high-severity claim.",
  },
  {
    role: "admin",
    email: "admin@tarnhollow.example",
    label: "Admin",
    does: "Owns the rulebook, the approved facts and the governance proposals.",
  },
];

export type GuideStep = {
  id: string;
  role: Role;
  title: string;
  body: string;
  href: string;
};

export const GUIDE: readonly GuideStep[] = [
  {
    id: "review",
    role: "creator",
    title: "See a review",
    body: "Open the LinkedIn post. Every finding cites the rule or approved fact it breaks. Open one to see why it was flagged.",
    href: "/content",
  },
  {
    id: "guardrail",
    role: "creator",
    title: "Hit a guardrail",
    body: "On the LinkedIn post, try to override the hidden-text finding. It's critical, so a creator can't. Only a reviewer can decide.",
    href: "/content",
  },
  {
    id: "resolve",
    role: "creator",
    title: "Fix and override",
    body: "On the agency blog, accept a suggested fix, and override a low or medium finding with a reason. Then send it for review.",
    href: "/content",
  },
  {
    id: "reviewer",
    role: "reviewer",
    title: "Review",
    body: "Clear a finding the AI was unsure about, and confirm or reject the creator's override.",
    href: "/queue",
  },
  {
    id: "approve",
    role: "manager",
    title: "Approve",
    body: "Approve the blog. A piece with a high-severity claim goes on to legal.",
    href: "/approvals",
  },
  {
    id: "signoff",
    role: "legal",
    title: "Sign off",
    body: "Sign off the blog, then open its version history and audit trail.",
    href: "/approvals",
  },
  {
    id: "impact",
    role: "admin",
    title: "Change a fact",
    body: "Edit fact F-002. The impact view lists every piece that cites it, with a re-review queued.",
    href: "/brand/facts",
  },
  {
    id: "governance",
    role: "admin",
    title: "Improve the rules",
    body: "A rule reviewers keep overriding gets a drafted amendment. It has passed the eval gate, and only you can approve it.",
    href: "/proposals",
  },
  {
    id: "trust",
    role: "admin",
    title: "Check the AI",
    body: "Open the blog: the masking preview shows what the model saw, the disclosure panel lists the models, and Replay re-runs a verdict. Replay a blog finding, not a banner one.",
    href: "/content",
  },
  {
    id: "graph",
    role: "admin",
    title: "Follow the memory",
    body: "Start from F-002 to see fact, claim and content linked.",
    href: "/graph",
  },
];

export function accountFor(role: Role): DemoAccount {
  const account = DEMO_ACCOUNTS.find((candidate) => candidate.role === role);
  if (!account) throw new Error(`No demo account for ${role}`);
  return account;
}

/** Signs in as a demo account and reloads, so every screen starts fresh. */
export async function switchTo(account: DemoAccount, href: string): Promise<void> {
  await login(account.email, DEMO_PASSWORD);
  window.location.assign(canRoleOpen(account.role, href) ? href : HOME_HREF);
}
