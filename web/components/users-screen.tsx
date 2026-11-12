"use client";

import { type FormEvent, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  ErrorNotice,
  SELECT_STYLE,
  ScreenHeader,
  errorMessage,
  useLoaded,
} from "@/components/brand-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ROLES, type Role } from "@/lib/contracts";
import {
  addPerson,
  changeRole,
  getPeople,
  removePerson,
} from "@/lib/workspace";

export function UsersScreen() {
  const { user, refreshWorkspace } = useAuth();
  const { data, error: loadError, reload } = useLoaded(getPeople);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      reload();
      refreshWorkspace();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    await run(async () => {
      await addPerson({
        email: String(values.get("email")),
        name: String(values.get("name")),
        role: String(values.get("role")) as Role,
        password: String(values.get("password")),
      });
      form.reset();
    });
  }

  return (
    <div className="mx-auto w-full max-w-4xl">
      <ScreenHeader
        title="People"
        summary="Everyone in this workspace and what they can do. You set each person's first password and hand it over."
      />
      <ErrorNotice message={error ?? loadError} />

      <form
        onSubmit={add}
        className="mt-6 grid gap-3 rounded-lg border bg-background p-4 sm:grid-cols-2"
      >
        <div className="flex flex-col gap-2">
          <Label htmlFor="person-name">Name</Label>
          <Input id="person-name" name="name" required maxLength={120} />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="person-email">Email</Label>
          <Input id="person-email" name="email" type="email" required />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="person-role">Role</Label>
          <select
            id="person-role"
            name="role"
            defaultValue="creator"
            className={SELECT_STYLE}
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="person-password">First password (8+ characters)</Label>
          <Input
            id="person-password"
            name="password"
            type="password"
            required
            minLength={8}
          />
        </div>
        <div className="sm:col-span-2">
          <Button type="submit">Add person</Button>
        </div>
      </form>

      <ul className="mt-6 divide-y rounded-lg border bg-background">
        {(data ?? []).map((person) => (
          <li
            key={person.id}
            className="flex flex-wrap items-center justify-between gap-3 p-4"
          >
            <p className="text-sm">
              <span className="block font-medium">{person.name}</span>
              <span className="block text-muted-foreground">{person.email}</span>
            </p>
            <div className="flex items-center gap-2">
              <label className="sr-only" htmlFor={`role-${person.id}`}>
                Role for {person.name}
              </label>
              <select
                id={`role-${person.id}`}
                value={person.role}
                className={SELECT_STYLE}
                onChange={(event) =>
                  run(() => changeRole(person.id, event.target.value as Role))
                }
              >
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
              <Button
                variant="outline"
                size="sm"
                disabled={person.id === user.id}
                onClick={() => {
                  if (window.confirm(`Remove ${person.name} from this workspace?`)) {
                    void run(() => removePerson(person.id));
                  }
                }}
              >
                Remove
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
