"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiUrl, ApiError } from "@/lib/api";
import {
  ACCEPTED_FILES,
  addVersion,
  channelLabel,
  type ContentDetail as Detail,
  getContent,
  LOCKED_STATES,
  REVIEWABLE_STATES,
  startReview,
  STATE_LABELS,
  versionFilePath,
} from "@/lib/content";

function errorMessage(caught: unknown): string {
  return caught instanceof ApiError
    ? caught.message
    : "Something went wrong. Try again in a moment.";
}

export function ContentDetail({ id }: { id: string }) {
  const { user } = useAuth();
  const router = useRouter();
  const [content, setContent] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let current = true;
    getContent(id).then(
      (loaded) => {
        if (current) setContent(loaded);
      },
      (caught: unknown) => {
        if (current) setError(errorMessage(caught));
      },
    );
    return () => {
      current = false;
    };
  }, [id]);

  if (!content) {
    return (
      <div className="mx-auto w-full max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Content</h1>
        {error ? (
          <p
            role="alert"
            className="mt-4 rounded-lg border border-destructive p-3 text-sm text-destructive"
          >
            {error}
          </p>
        ) : (
          <p role="status" className="mt-4 text-sm text-muted-foreground">
            Loading…
          </p>
        )}
      </div>
    );
  }

  const latest = content.versions[0];
  const isOwner = content.creator_id === user.id;
  const canEdit = isOwner && !LOCKED_STATES.includes(content.state);
  const canStartReview =
    isOwner && REVIEWABLE_STATES.includes(content.state);
  // A review of an older version shouldn't be mistaken for one of the latest.
  const reviewIsCurrent =
    content.latest_review?.content_version_id === latest.id;

  async function handleNewVersion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setPending(true);
    setError(null);
    try {
      setContent(await addVersion(id, new FormData(form)));
      form.reset();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPending(false);
    }
  }

  async function handleStartReview() {
    setPending(true);
    setError(null);
    try {
      await startReview(id);
      router.push(`/content/${id}/review`);
    } catch (caught) {
      setError(errorMessage(caught));
      setPending(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl">
      <Link
        href="/content"
        className="text-sm text-muted-foreground underline underline-offset-2"
      >
        Back to content
      </Link>

      <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">
          {content.title}
        </h1>
        <div className="flex gap-2">
          {content.latest_review && (
            <Button
              variant="outline"
              render={<Link href={`/content/${id}/review`} />}
            >
              Open review
            </Button>
          )}
          {canStartReview && !reviewIsCurrent && (
            <Button onClick={handleStartReview} disabled={pending}>
              Start review
            </Button>
          )}
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">State</dt>
          <dd className="font-medium">{STATE_LABELS[content.state]}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Channel</dt>
          <dd className="font-medium">{channelLabel(content.channel)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Source</dt>
          <dd className="font-medium">{content.source}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Data class</dt>
          <dd className="font-medium capitalize">{content.data_class}</dd>
        </div>
      </dl>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-destructive p-3 text-sm text-destructive"
        >
          {error}
        </p>
      )}

      <section aria-labelledby="latest-heading" className="mt-8">
        <h2 id="latest-heading" className="text-lg font-semibold">
          Latest version
        </h2>
        {latest.file_name && (
          <p className="mt-2 text-sm">
            <a
              href={apiUrl(versionFilePath(latest.id))}
              className="underline underline-offset-2"
            >
              {latest.file_name}
            </a>
          </p>
        )}
        {latest.text && (
          <p className="mt-2 rounded-lg border p-4 text-sm whitespace-pre-wrap">
            {latest.text}
          </p>
        )}
      </section>

      {canEdit && (
        <section aria-labelledby="edit-heading" className="mt-8">
          <h2 id="edit-heading" className="text-lg font-semibold">
            Add a new version
          </h2>
          <form
            key={latest.id}
            onSubmit={handleNewVersion}
            className="mt-3 flex flex-col gap-4"
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="text">Edit the text</Label>
              <Textarea
                id="text"
                name="text"
                rows={8}
                defaultValue={latest.text}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="file">Or upload a replacement file</Label>
              <Input
                id="file"
                name="file"
                type="file"
                accept={ACCEPTED_FILES}
              />
            </div>
            <div>
              <Button type="submit" variant="outline" disabled={pending}>
                Save as new version
              </Button>
            </div>
          </form>
        </section>
      )}

      <section aria-labelledby="history-heading" className="mt-8">
        <h2 id="history-heading" className="text-lg font-semibold">
          Version history
        </h2>
        <ol className="mt-3 divide-y rounded-lg border text-sm">
          {content.versions.map((version) => (
            <li
              key={version.id}
              className="flex flex-wrap justify-between gap-2 px-4 py-2"
            >
              <span className="font-medium">Version {version.version}</span>
              <span className="text-muted-foreground">
                {new Date(version.created_at).toLocaleString()}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
