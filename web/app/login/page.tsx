import { Check } from "lucide-react";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DemoRolePicker, StartDemo } from "@/components/demo-logins";
import { LoginForm } from "@/components/login-form";
import { SignupForm } from "@/components/signup-form";
import { DEMO_MODE } from "@/lib/demo";
import { safeNextPath } from "@/lib/navigation";

export const metadata: Metadata = { title: "Sign in" };

// Whether visitors can create their own workspace. The API refuses it unless it is on there too.
const SIGNUP_OPEN = process.env.NEXT_PUBLIC_MULTI_TENANT_SIGNUP === "true";

function Card({
  title,
  summary,
  main = false,
  children,
}: {
  title: string;
  summary: string;
  // The first card carries the page's heading.
  main?: boolean;
  children: ReactNode;
}) {
  const Heading = main ? "h1" : "h2";
  return (
    <section className="w-full rounded-xl border bg-background p-8">
      <span className="flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <Check aria-hidden="true" className="size-5" strokeWidth={3} />
      </span>
      <Heading className="mt-4 text-2xl font-semibold tracking-tight">
        {title}
      </Heading>
      <p className="mt-1 mb-6 text-sm text-muted-foreground">{summary}</p>
      {children}
    </section>
  );
}

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { next } = await searchParams;
  const target = safeNextPath(next);

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted p-6">
      <div
        className={`grid w-full items-start gap-6 ${
          SIGNUP_OPEN ? "max-w-4xl md:grid-cols-2" : "max-w-sm"
        }`}
      >
        {DEMO_MODE ? (
          <Card
            main
            title="Explore the Tarnhollow demo"
            summary="No account needed. The tour shows you what to click and why."
          >
            <div className="flex flex-col gap-6">
              <StartDemo />
              <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-border" />
                <span className="text-xs text-muted-foreground">
                  or jump straight to a role
                </span>
                <div className="h-px flex-1 bg-border" />
              </div>
              <DemoRolePicker />
            </div>
          </Card>
        ) : (
          <Card
            main
            title="Sign in to BrandLint"
            summary="Use your work email and password."
          >
            <LoginForm next={target} />
          </Card>
        )}

        {SIGNUP_OPEN && (
          <Card
            title="Create your own workspace"
            summary="Your own empty workspace, separate from everyone else's. It lasts a week."
          >
            <SignupForm />
            {DEMO_MODE && (
              <details className="mt-6 border-t pt-4">
                <summary className="cursor-pointer text-sm font-medium">
                  Already have a workspace? Sign in
                </summary>
                <div className="mt-4">
                  <LoginForm next={target} />
                </div>
              </details>
            )}
          </Card>
        )}
      </div>
    </main>
  );
}
