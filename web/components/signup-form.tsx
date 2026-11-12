"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { ErrorNotice, errorMessage } from "@/components/brand-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createWorkspace } from "@/lib/workspace";

export function SignupForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      await createWorkspace({
        workspace_name: String(form.get("workspace_name")),
        name: String(form.get("name")),
        email: String(form.get("signup_email")),
        password: String(form.get("signup_password")),
      });
      router.replace("/content");
    } catch (caught) {
      setError(errorMessage(caught));
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <ErrorNotice message={error} />
      <div className="flex flex-col gap-2">
        <Label htmlFor="workspace_name">Workspace name</Label>
        <Input
          id="workspace_name"
          name="workspace_name"
          required
          minLength={2}
          maxLength={80}
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="name">Your name</Label>
        <Input id="name" name="name" autoComplete="name" required maxLength={120} />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="signup_email">Email</Label>
        <Input
          id="signup_email"
          name="signup_email"
          type="email"
          autoComplete="email"
          required
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="signup_password">Password (at least 8 characters)</Label>
        <Input
          id="signup_password"
          name="signup_password"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          maxLength={128}
        />
      </div>
      <Button type="submit" disabled={pending}>
        {pending ? "Creating…" : "Create workspace"}
      </Button>
    </form>
  );
}
