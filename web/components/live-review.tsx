"use client";

import { Radio, TriangleAlert, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  describe,
  followContent,
  type LiveEvent,
  lookAt,
  type Presence,
} from "@/lib/collab";

type Note = { id: number; text: string; warn: boolean };

function actorOf(event: LiveEvent): string | null {
  return "actor" in event ? event.actor.id : null;
}

const MAX_NOTES = 4;
const NOTE_MS = 12000;

// Shows who else is on this piece, what they just did, and when two people clash. A
// change by someone else reloads the board through `onRemoteChange`, so nobody decides
// on a stale screen. It only watches: every decision is still made, and checked, by the
// server.
export function LiveReview({
  contentId,
  selectedId,
  onRemoteChange,
}: {
  contentId: string;
  selectedId: string | null;
  onRemoteChange: (kind: "board" | "comments") => void;
}) {
  const [presence, setPresence] = useState<Presence>({ viewers: [], contested: [] });
  const [me, setMe] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState<Note[]>([]);
  const counter = useRef(0);
  const change = useRef(onRemoteChange);
  useEffect(() => {
    change.current = onRemoteChange;
  });

  useEffect(() => {
    const push = (text: string, warn: boolean) => {
      const id = (counter.current += 1);
      setNotes((all) => [...all.slice(-(MAX_NOTES - 1)), { id, text, warn }]);
      if (!warn) {
        setTimeout(() => setNotes((all) => all.filter((n) => n.id !== id)), NOTE_MS);
      }
    };
    let self: string | null = null;
    const handle = (event: LiveEvent) => {
      if (event.kind === "hello") {
        self = event.you.id;
        setMe(event.you.id);
        setPresence(event.presence);
        return;
      }
      if (event.kind === "presence") return setPresence(event.presence);
      if (event.kind === "resync") return change.current("board");
      const conflict = event.kind === "conflict";
      const mine = actorOf(event) === self;
      const text = describe(event);
      // Your own actions need no announcement, but a clash always does.
      if (text && (conflict || !mine)) push(text, conflict);
      if (event.kind === "comment") change.current("comments");
      else if (conflict || !mine) change.current("board");
    };
    return followContent(contentId, handle, setOpen);
  }, [contentId]);

  // Tell the others which finding this person has open. Best effort: a failure here
  // changes nothing about the review.
  useEffect(() => {
    if (!open) return;
    lookAt(contentId, selectedId).catch(() => {});
  }, [contentId, selectedId, open]);

  const others = presence.viewers.filter((viewer) => viewer.id !== me);
  const contested = selectedId !== null && presence.contested.includes(selectedId);

  return (
    <section
      aria-label="Live review"
      // Pinned under the top bar, so a warning stays in view however far you scroll.
      className="sticky top-14 z-20 mt-4 flex flex-col gap-2 rounded-xl border bg-card p-3 text-sm shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="inline-flex items-center gap-1 font-medium">
          <Radio
            aria-hidden="true"
            className={open ? "size-4 text-emerald-600" : "size-4 text-muted-foreground"}
          />
          {open ? "Live" : "Reconnecting…"}
        </span>
        {others.length === 0 ? (
          <span className="text-muted-foreground">You&apos;re the only one here.</span>
        ) : (
          <ul aria-label="Also reviewing" className="flex flex-wrap gap-2">
            {others.map((viewer) => (
              <li
                key={viewer.id}
                className="rounded-full bg-muted px-2 py-0.5 text-xs"
              >
                <span className="font-medium">{viewer.name}</span>{" "}
                <span className="text-muted-foreground">
                  {viewer.role}
                  {viewer.finding_id ? " · on a finding" : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {contested && (
        <p role="status" className="flex items-center gap-1 text-amber-900">
          <TriangleAlert aria-hidden="true" className="size-4" />
          Someone else has this finding open too. Check what they decide before you do.
        </p>
      )}
      {notes.length > 0 && (
        <ul aria-live="polite" className="flex flex-col gap-1">
          {notes.map((note) => (
            <li
              key={note.id}
              className={
                note.warn
                  ? "flex items-start justify-between gap-2 rounded-lg border border-amber-400 bg-amber-50 p-2 text-amber-950"
                  : "rounded-lg bg-muted p-2"
              }
            >
              <span>{note.text}</span>
              {note.warn && (
                <button
                  type="button"
                  aria-label="Dismiss"
                  className="shrink-0 rounded p-0.5 hover:bg-amber-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  onClick={() => setNotes((all) => all.filter((n) => n.id !== note.id))}
                >
                  <X aria-hidden="true" className="size-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
