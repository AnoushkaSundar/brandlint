"use client";

import { useState } from "react";

import { errorMessage } from "@/components/brand-ui";
import {
  type Disclosure,
  type MaskingPreview,
  getDisclosure,
  getMaskingPreview,
} from "@/lib/governance";

const ROUTE_LABELS: Record<string, string> = {
  cloud: "Cloud model, after masking",
  local: "Local model, nothing left the server",
};

/** What the models saw for a review: loaded only when someone opens it. */
export function DisclosurePanel({ reviewId }: { reviewId: string }) {
  const [disclosure, setDisclosure] = useState<Disclosure | null>(null);
  const [preview, setPreview] = useState<MaskingPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requested, setRequested] = useState(false);

  async function load() {
    if (requested) return;
    setRequested(true);
    try {
      const [loadedDisclosure, loadedPreview] = await Promise.all([
        getDisclosure(reviewId),
        getMaskingPreview(reviewId),
      ]);
      setDisclosure(loadedDisclosure);
      setPreview(loadedPreview);
    } catch (caught) {
      setError(errorMessage(caught));
      setRequested(false);
    }
  }

  const masked = Object.entries(disclosure?.masked ?? {});
  return (
    <details
      className="mt-6 rounded-lg border p-4"
      onToggle={(event) => {
        if ((event.currentTarget as HTMLDetailsElement).open) load();
      }}
    >
      <summary className="cursor-pointer font-medium">
        What the models saw
      </summary>
      {error && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      )}
      {requested && !disclosure && !error && (
        <p role="status" className="mt-3 text-sm text-muted-foreground">
          Loading…
        </p>
      )}
      {disclosure && (
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted-foreground">Models used</dt>
            <dd className="font-medium">
              {disclosure.models.length
                ? disclosure.models.join(", ")
                : "No model was called"}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Route</dt>
            <dd className="font-medium">
              {disclosure.routes.length
                ? disclosure.routes
                    .map((route) => ROUTE_LABELS[route] ?? route)
                    .join("; ")
                : "None"}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Masked before sending</dt>
            <dd className="font-medium">
              {masked.length
                ? masked
                    .map(([entity, count]) => `${count} × ${entity}`)
                    .join(", ")
                : "Nothing"}
            </dd>
          </div>
        </dl>
      )}
      {preview && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <section aria-labelledby={`original-${reviewId}`}>
            <h3
              id={`original-${reviewId}`}
              className="text-sm text-muted-foreground"
            >
              Your text
            </h3>
            <p className="mt-1 rounded-md border p-3 text-sm whitespace-pre-wrap">
              {preview.original}
            </p>
          </section>
          <section aria-labelledby={`sent-${reviewId}`}>
            <h3
              id={`sent-${reviewId}`}
              className="text-sm text-muted-foreground"
            >
              What the model received
            </h3>
            <p className="mt-1 rounded-md border bg-muted/30 p-3 text-sm whitespace-pre-wrap">
              {preview.sent}
            </p>
          </section>
        </div>
      )}
    </details>
  );
}
