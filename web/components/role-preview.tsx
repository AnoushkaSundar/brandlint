"use client";

import { usePathname, useRouter } from "next/navigation";

import { useRole } from "@/components/role-provider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ROLES, type Role } from "@/lib/contracts";
import { canRoleOpen, HOME_HREF } from "@/lib/navigation";

const ROLE_LABELS: Record<Role, string> = {
  creator: "Creator",
  reviewer: "Reviewer",
  manager: "Manager",
  legal: "Legal",
  admin: "Admin",
};

const ROLE_OPTIONS = ROLES.map((value) => ({
  value,
  label: ROLE_LABELS[value],
}));

// Temporary control for checking the navigation per role. Remove it in block 2.
export function RolePreview() {
  const { role, setRole } = useRole();
  const pathname = usePathname();
  const router = useRouter();

  function handleChange(next: Role | null) {
    if (!next) return;
    setRole(next);
    if (!canRoleOpen(next, pathname)) {
      router.replace(HOME_HREF);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span aria-hidden="true" className="text-sm text-muted-foreground">
        Preview role
      </span>
      <Select items={ROLE_OPTIONS} value={role} onValueChange={handleChange}>
        <SelectTrigger aria-label="Preview role" className="w-28">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ROLE_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
