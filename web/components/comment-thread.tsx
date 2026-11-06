"use client";

import { type FormEvent, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { type Comment, type CommentInput, formatTime } from "@/lib/reviewDesk";

function CommentForm({
  label,
  submitLabel,
  onSubmit,
  onDone,
}: {
  label: string;
  submitLabel: string;
  onSubmit: (body: string) => Promise<void>;
  onDone?: () => void;
}) {
  const fieldId = useId();
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    onSubmit(body.trim())
      .then(
        () => {
          setBody("");
          onDone?.();
        },
        (caught: ApiError) => setError(caught.message),
      )
      .finally(() => setBusy(false));
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <Label htmlFor={fieldId}>{label}</Label>
      <Textarea
        id={fieldId}
        value={body}
        onChange={(event) => setBody(event.target.value)}
      />
      {error && (
        <p role="alert" className="border-l-2 border-destructive pl-2">
          {error}
        </p>
      )}
      <div>
        <Button type="submit" size="sm" disabled={busy || !body.trim()}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

function Entry({
  comment,
  replies,
  onReply,
}: {
  comment: Comment;
  replies: readonly Comment[];
  onReply: (body: string) => Promise<void>;
}) {
  const [replying, setReplying] = useState(false);

  return (
    <li className="flex flex-col gap-1">
      <p>
        <span className="font-medium">{comment.author}</span>{" "}
        <span className="text-muted-foreground">
          {formatTime(comment.created_at)}
        </span>
      </p>
      <p className="whitespace-pre-wrap">{comment.body}</p>
      {comment.mentions.length > 0 && (
        <p className="text-muted-foreground">
          Mentions {comment.mentions.join(", ")}
        </p>
      )}
      {replies.length > 0 && (
        <ul className="mt-1 flex flex-col gap-2 border-l-2 pl-3">
          {replies.map((reply) => (
            <li key={reply.id}>
              <p>
                <span className="font-medium">{reply.author}</span>{" "}
                <span className="text-muted-foreground">
                  {formatTime(reply.created_at)}
                </span>
              </p>
              <p className="whitespace-pre-wrap">{reply.body}</p>
            </li>
          ))}
        </ul>
      )}
      {replying ? (
        <CommentForm
          label={`Reply to ${comment.author}`}
          submitLabel="Send reply"
          onSubmit={onReply}
          onDone={() => setReplying(false)}
        />
      ) : (
        <div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={`Reply to ${comment.author}`}
            onClick={() => setReplying(true)}
          >
            Reply
          </Button>
        </div>
      )}
    </li>
  );
}

export function CommentThread({
  label,
  comments,
  versionId,
  findingId = null,
  onPost,
}: {
  label: string;
  comments: readonly Comment[];
  versionId: string;
  findingId?: string | null;
  onPost: (input: CommentInput) => Promise<void>;
}) {
  const inThread = comments.filter((item) => item.finding_id === findingId);
  const roots = inThread.filter((item) => item.parent_id === null);

  const post = (body: string, parentId: string | null) =>
    onPost({
      body,
      content_version_id: versionId,
      finding_id: findingId,
      parent_id: parentId,
    });

  return (
    <div className="flex flex-col gap-3 text-sm">
      {roots.length > 0 && (
        <ul className="flex flex-col gap-3">
          {roots.map((comment) => (
            <Entry
              key={comment.id}
              comment={comment}
              replies={inThread.filter((item) => item.parent_id === comment.id)}
              onReply={(body) => post(body, comment.id)}
            />
          ))}
        </ul>
      )}
      <CommentForm
        label={label}
        submitLabel="Post comment"
        onSubmit={(body) => post(body, null)}
      />
      <p className="text-muted-foreground">
        Type @ and someone&apos;s sign-in name to mention them, such as
        @reviewer.
      </p>
    </div>
  );
}
