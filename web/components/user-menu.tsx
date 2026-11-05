"use client";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import type { Role } from "@/lib/contracts";

const ROLE_LABELS: Record<Role, string> = {
  creator: "Creator",
  reviewer: "Reviewer",
  manager: "Manager",
  legal: "Legal",
  admin: "Admin",
};

export function UserMenu() {
  const { user, signOut } = useAuth();

  return (
    <div className="flex items-center gap-3">
      <p className="text-right text-sm leading-tight">
        <span className="block font-medium">{user.name}</span>
        <span className="block text-muted-foreground">
          {ROLE_LABELS[user.role]}
        </span>
      </p>
      <Button variant="outline" size="sm" onClick={signOut}>
        Sign out
      </Button>
    </div>
  );
}
