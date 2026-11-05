import type { Metadata } from "next";

import { getNavItem } from "@/lib/navigation";

export function placeholderMetadata(href: string): Metadata {
  return { title: getNavItem(href).title };
}

// Holds a route open until its screen is built, so no navigation link is a dead end.
export function PlaceholderPage({ href }: { href: string }) {
  const { title, summary } = getNavItem(href);

  return (
    <div className="mx-auto w-full max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-muted-foreground">{summary}</p>
      <p className="mt-6 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
        This screen hasn&apos;t been built yet.
      </p>
    </div>
  );
}
