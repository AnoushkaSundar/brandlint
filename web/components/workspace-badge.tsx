"use client";

import { useAuth } from "@/components/auth-provider";

// Says which workspace you are in, so two workspaces are never mistaken for each other.
export function WorkspaceBadge() {
  const { workspace } = useAuth();
  if (!workspace) return null;

  return (
    <p className="flex items-center gap-2 text-sm">
      <span className="font-medium">{workspace.name}</span>
      {workspace.kind === "demo" && (
        <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
          Demo workspace
        </span>
      )}
    </p>
  );
}
