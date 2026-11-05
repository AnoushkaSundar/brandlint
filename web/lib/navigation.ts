import {
  BookOpen,
  ChartColumn,
  FilePen,
  FileText,
  ImageIcon,
  ListChecks,
  type LucideIcon,
  Network,
  Quote,
  ScrollText,
  ShieldCheck,
  Stamp,
} from "lucide-react";

import type { Role } from "@/lib/contracts";

export type NavItem = {
  title: string;
  href: string;
  summary: string;
  icon: LucideIcon;
  roles: readonly Role[];
};

export type NavGroup = {
  label: string;
  items: readonly NavItem[];
};

// Every role can reach this, so it is the safe landing page.
export const HOME_HREF = "/content";

// This decides what the navigation shows. It is not access control: the API
// enforces permissions on every request.
export const NAV_GROUPS: readonly NavGroup[] = [
  {
    label: "Work",
    items: [
      {
        title: "Content",
        href: "/content",
        summary: "Submit drafts and follow them through review and approval.",
        icon: FileText,
        roles: ["creator", "reviewer", "manager", "legal", "admin"],
      },
      {
        title: "Review queue",
        href: "/queue",
        summary:
          "UNSURE findings, pending overrides and spot-checks, sorted by severity.",
        icon: ListChecks,
        roles: ["reviewer"],
      },
      {
        title: "Approvals",
        href: "/approvals",
        summary: "Pieces waiting for manager approval or legal sign-off.",
        icon: Stamp,
        roles: ["manager", "legal"],
      },
    ],
  },
  {
    label: "Brand",
    items: [
      {
        title: "Rulebook",
        href: "/brand/rulebook",
        summary: "Upload guidelines, resolve conflicts and approve rules.",
        icon: BookOpen,
        roles: ["admin"],
      },
      {
        title: "Facts",
        href: "/brand/facts",
        summary: "Approved facts with their source, owner and expiry date.",
        icon: ShieldCheck,
        roles: ["admin"],
      },
      {
        title: "Terms",
        href: "/brand/terms",
        summary: "Preferred terms, banned variants and product renames.",
        icon: Quote,
        roles: ["admin"],
      },
      {
        title: "Assets",
        href: "/brand/assets",
        summary: "Approved logos, palettes and images.",
        icon: ImageIcon,
        roles: ["admin"],
      },
    ],
  },
  {
    label: "Governance",
    items: [
      {
        title: "Insights",
        href: "/insights",
        summary: "Violations, override rates and guideline gaps across teams.",
        icon: ChartColumn,
        roles: ["manager", "admin"],
      },
      {
        title: "Proposals",
        href: "/proposals",
        summary:
          "Suggested rule amendments, with their evidence and eval results.",
        icon: FilePen,
        roles: ["admin"],
      },
      {
        title: "Memory graph",
        href: "/graph",
        summary: "How facts connect to claims and content.",
        icon: Network,
        roles: ["admin"],
      },
      {
        title: "Audit log",
        href: "/audit",
        summary: "Every decision, state change and rule change.",
        icon: ScrollText,
        roles: ["manager", "admin"],
      },
    ],
  },
];

export function navForRole(role: Role): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => item.roles.includes(role)),
  })).filter((group) => group.items.length > 0);
}

export function getNavItem(href: string): NavItem {
  const item = NAV_GROUPS.flatMap((group) => group.items).find(
    (candidate) => candidate.href === href,
  );
  if (!item) {
    throw new Error(`No navigation item for ${href}`);
  }
  return item;
}

export function isActivePath(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

// Only paths on this site, so a crafted link can't send someone elsewhere after sign-in.
export function safeNextPath(next: unknown): string {
  const isLocalPath =
    typeof next === "string" &&
    next.startsWith("/") &&
    !next.startsWith("//") &&
    !next.startsWith("/\\");
  return isLocalPath ? next : HOME_HREF;
}

export function canRoleOpen(role: Role, pathname: string): boolean {
  return navForRole(role)
    .flatMap((group) => group.items)
    .some((item) => isActivePath(pathname, item.href));
}
