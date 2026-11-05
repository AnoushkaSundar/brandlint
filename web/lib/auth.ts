import { apiFetch } from "@/lib/api";
import type { Role } from "@/lib/contracts";

export type User = {
  id: string;
  email: string;
  name: string;
  role: Role;
  tag: string | null;
};

export function fetchCurrentUser(): Promise<User> {
  return apiFetch<User>("/auth/me");
}

export async function login(email: string, password: string): Promise<User> {
  const { user } = await apiFetch<{ user: User }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  return user;
}

export function logout(): Promise<void> {
  return apiFetch<void>("/auth/logout", { method: "POST" });
}
