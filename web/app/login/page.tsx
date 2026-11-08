import { Check } from "lucide-react";
import type { Metadata } from "next";

import { DemoRolePicker, StartDemo } from "@/components/demo-logins";
import { LoginForm } from "@/components/login-form";
import { DEMO_MODE } from "@/lib/demo";
import { safeNextPath } from "@/lib/navigation";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { next } = await searchParams;

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted p-6">
      <div className="w-full max-w-sm rounded-xl border bg-background p-8">
        <span className="flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Check aria-hidden="true" className="size-5" strokeWidth={3} />
        </span>
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">
          {DEMO_MODE ? "Try BrandLint" : "Sign in to BrandLint"}
        </h1>
        <p className="mt-1 mb-6 text-sm text-muted-foreground">
          {DEMO_MODE
            ? "No account needed. The tour shows you what to click and why."
            : "Use your work email and password."}
        </p>
        {DEMO_MODE ? (
          <div className="flex flex-col gap-6">
            <StartDemo />
            <div className="flex items-center gap-3">
              <div className="h-px flex-1 bg-border" />
              <span className="text-xs text-muted-foreground">or jump straight to a role</span>
              <div className="h-px flex-1 bg-border" />
            </div>
            <DemoRolePicker />
          </div>
        ) : (
          <LoginForm next={safeNextPath(next)} />
        )}
      </div>
    </main>
  );
}
