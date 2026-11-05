"use client";

import {
  createContext,
  type ReactNode,
  useContext,
  useState,
} from "react";

import type { Role } from "@/lib/contracts";

type RoleContextValue = {
  role: Role;
  setRole: (role: Role) => void;
};

const RoleContext = createContext<RoleContextValue | null>(null);

// Stand-in until sign-in lands in block 2, when the role comes from the JWT.
// Starts on the least-privileged role.
export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role>("creator");

  return (
    <RoleContext.Provider value={{ role, setRole }}>
      {children}
    </RoleContext.Provider>
  );
}

export function useRole(): RoleContextValue {
  const value = useContext(RoleContext);
  if (!value) {
    throw new Error("useRole must be used inside RoleProvider");
  }
  return value;
}
