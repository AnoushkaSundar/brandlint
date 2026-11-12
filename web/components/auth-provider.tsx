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
import type { Workspace } from "@/lib/contracts";
import { fetchWorkspace } from "@/lib/workspace";
import { canRoleOpen, HOME_HREF } from "@/lib/navigation";

type AuthContextValue = {
  user: User;
  // Null until it loads, or if it can't be read: the shell works without it.
  workspace: Workspace | null;
  refreshWorkspace: () => void;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

// Keeps the signed-in user for the shell and redirects when there isn't one. This
// only shapes the UI: the API enforces every permission on every request.
export function AuthProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [workspaceVersion, setWorkspaceVersion] = useState(0);

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

  useEffect(() => {
    if (!user) return;
    let current = true;
    fetchWorkspace().then(
      (loaded) => {
        if (current) setWorkspace(loaded);
      },
      () => {
        if (current) setWorkspace(null);
      },
    );
    return () => {
      current = false;
    };
  }, [user, pathname, workspaceVersion]);

  // The page's own title, with the workspace it is in.
  useEffect(() => {
    if (!workspace) return;
    const timer = window.setTimeout(() => {
      const page = document.title.split(" · ")[0];
      document.title = `${page} · ${workspace.name}`;
    }, 0);
    return () => window.clearTimeout(timer);
  }, [workspace, pathname]);

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
    <AuthContext.Provider
      value={{
        user,
        workspace,
        refreshWorkspace: () => setWorkspaceVersion((version) => version + 1),
        signOut,
      }}
    >
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
