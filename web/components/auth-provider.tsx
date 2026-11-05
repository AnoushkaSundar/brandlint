"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";

import { fetchCurrentUser, logout, type User } from "@/lib/auth";
import { canRoleOpen, HOME_HREF } from "@/lib/navigation";

type AuthContextValue = {
  user: User;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

// Keeps the signed-in user for the shell and redirects when there isn't one. This
// only shapes the UI: the API enforces every permission on every request.
export function AuthProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  // Runs on every navigation, so an expired session or a role change shows up.
  useEffect(() => {
    let current = true;
    fetchCurrentUser().then(
      (signedIn) => {
        if (current) setUser(signedIn);
      },
      () => {
        if (current) {
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
        }
      },
    );
    return () => {
      current = false;
    };
  }, [pathname, router]);

  const allowed = user !== null && canRoleOpen(user.role, pathname);

  useEffect(() => {
    if (user && !allowed) router.replace(HOME_HREF);
  }, [user, allowed, router]);

  if (!allowed) {
    return (
      <p role="status" className="p-6 text-sm text-muted-foreground">
        Loading…
      </p>
    );
  }

  async function signOut() {
    await logout();
    setUser(null);
    router.replace("/login");
  }

  return (
    <AuthContext.Provider value={{ user, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return value;
}
