import { CircleAlert, Info, OctagonAlert, TriangleAlert } from "lucide-react";

import type { Severity } from "@/lib/contracts";
import { SEVERITY_LABELS } from "@/lib/findingLabels";
import { cn } from "@/lib/utils";

// Solid for the two levels only a reviewer can clear, soft for the rest. Each pair
// keeps at least 4.5:1 contrast, and the icon carries the level for anyone who
// can't tell the colours apart.
const STYLE: Record<Severity, string> = {
  critical: "bg-red-700 text-white",
  high: "bg-orange-700 text-white",
  medium: "bg-amber-100 text-amber-900 ring-1 ring-amber-300 ring-inset",
  low: "bg-sky-100 text-sky-900 ring-1 ring-sky-300 ring-inset",
};

const ICON = {
  critical: OctagonAlert,
  high: TriangleAlert,
  medium: CircleAlert,
  low: Info,
} satisfies Record<Severity, unknown>;

/** The coloured left edge of a card, by severity. */
export const SEVERITY_EDGE: Record<Severity, string> = {
  critical: "border-l-red-700",
  high: "border-l-orange-600",
  medium: "border-l-amber-400",
  low: "border-l-sky-400",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const Icon = ICON[severity];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
        STYLE[severity],
      )}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {SEVERITY_LABELS[severity]}
    </span>
  );
}
