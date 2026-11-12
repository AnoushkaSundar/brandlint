import { apiFetch } from "@/lib/api";
import type { Role, Workspace } from "@/lib/contracts";

export function fetchWorkspace(): Promise<Workspace> {
  return apiFetch<Workspace>("/orgs/current");
}

export type SignupInput = {
  workspace_name: string;
  name: string;
  email: string;
  password: string;
};

/** Creates a sandbox workspace and signs its first admin in (the API sets the cookie). */
export function createWorkspace(input: SignupInput): Promise<unknown> {
  return apiFetch("/orgs", { method: "POST", body: JSON.stringify(input) });
}

/** Copies the Tarnhollow guidelines into the caller's own workspace. */
export function loadSampleGuidelines(): Promise<unknown> {
  return apiFetch("/admin/sample-guidelines", { method: "POST" });
}

/** Wipes and re-seeds the demo workspace. The API refuses it for any other. */
export function resetDemo(): Promise<unknown> {
  return apiFetch("/admin/demo/reset", { method: "POST" });
}

export type Person = {
  id: string;
  email: string;
  name: string;
  role: Role;
  tag: string | null;
};

export type PersonInput = {
  email: string;
  name: string;
  role: Role;
  password: string;
};

export function getPeople(): Promise<Person[]> {
  return apiFetch<Person[]>("/admin/users");
}

export function addPerson(input: PersonInput): Promise<Person> {
  return apiFetch<Person>("/admin/users", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function changeRole(id: string, role: Role): Promise<Person> {
  return apiFetch<Person>(`/admin/users/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function removePerson(id: string): Promise<void> {
  return apiFetch<void>(`/admin/users/${id}`, { method: "DELETE" });
}
