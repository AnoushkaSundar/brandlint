import { Check } from "lucide-react";
import type { Metadata } from "next";

import { DemoLogins } from "@/components/demo-logins";
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
          Sign in to BrandLint
        </h1>
        <p className="mt-1 mb-6 text-sm text-muted-foreground">
          Use your work email and password.
        </p>
        <LoginForm next={safeNextPath(next)} />
        {DEMO_MODE && <DemoLogins next={safeNextPath(next)} />}
      </div>
    </main>
  );
}
