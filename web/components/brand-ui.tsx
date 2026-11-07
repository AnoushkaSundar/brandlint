"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";

export const SELECT_STYLE =
  "h-9 rounded-md border bg-background px-2 text-sm text-foreground";

export function ErrorNotice({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="mt-4 rounded-lg border border-destructive p-3 text-sm text-destructive"
    >
      {message}
    </p>
  );
}

export function SavedNotice({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="mt-4 rounded-lg border p-3 text-sm">
      {children}
    </p>
  );
}

export function ScreenHeader({
  title,
  summary,
}: {
  title: string;
  summary: string;
}) {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-muted-foreground">{summary}</p>
    </>
  );
}

export function errorMessage(caught: unknown): string {
  return caught instanceof ApiError
    ? caught.message
    : "Something went wrong. Try again in a moment.";
}

/** Loads data once, and again whenever reload() is called. */
export function useLoaded<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ticket, setTicket] = useState(0);

  useEffect(() => {
    let current = true;
    load().then(
      (loaded) => {
        if (current) {
          setData(loaded);
          setError(null);
        }
      },
      (caught) => {
        if (current) setError(errorMessage(caught));
      },
    );
    return () => {
      current = false;
    };
  }, [load, ticket]);

  const reload = useCallback(() => setTicket((value) => value + 1), []);
  return { data, error, reload };
}
