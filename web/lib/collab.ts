import { apiFetch, apiUrl } from "@/lib/api";

export type Person = { id: string; name: string; role: string };
export type Viewer = Person & { finding_id: string | null };
export type Presence = { viewers: Viewer[]; contested: string[] };

export type LiveEvent =
  | { kind: "hello"; you: Person; presence: Presence }
  | { kind: "presence"; presence: Presence }
  | {
      kind: "decision";
      finding_id: string;
      actor: Person;
      action: string;
      status: string;
      reason: string | null;
    }
  | { kind: "state"; from: string; to: string; actor: Person; reason: string | null }
  | { kind: "comment"; finding_id: string | null; actor: Person }
  | {
      kind: "conflict";
      finding_id: string;
      first: { person: Person; action: string; status: string };
      second: { person: Person; action: string; status: string };
      within_seconds: number;
    }
  | { kind: "resync" };

const ACTION_WORDS: Record<string, string> = {
  accept_fix: "accepted a fix",
  edit_fix: "edited a fix",
  override: "asked to override a finding",
  confirm_override: "confirmed an override",
  reject_override: "rejected an override",
  resolve: "resolved a finding",
};

export function describe(event: LiveEvent): string | null {
  switch (event.kind) {
    case "decision":
      return `${event.actor.name} ${ACTION_WORDS[event.action] ?? "made a decision"}.`;
    case "state":
      return `${event.actor.name} moved this to ${event.to.replace(/_/g, " ")}.`;
    case "comment":
      return `${event.actor.name} left a comment.`;
    case "conflict":
      return (
        `${event.first.person.name} and ${event.second.person.name} both settled ` +
        `this finding within ${Math.max(1, Math.round(event.within_seconds))} seconds. ` +
        "Check it before you go on."
      );
    default:
      return null;
  }
}

function presenceOf(data: { viewers?: Viewer[]; contested?: string[] }): Presence {
  return { viewers: data.viewers ?? [], contested: data.contested ?? [] };
}

/**
 * Follows a piece of content live. EventSource reconnects by itself and sends
 * Last-Event-ID, so a dropped connection catches up on what it missed. Returns a
 * function that closes it.
 */
export function followContent(
  contentId: string,
  onEvent: (event: LiveEvent) => void,
  onConnection: (open: boolean) => void,
): () => void {
  const source = new EventSource(apiUrl(`/collab/content/${contentId}/events`), {
    withCredentials: true,
  });
  const listen = (name: string, build: (data: never) => LiveEvent) =>
    source.addEventListener(name, (message) => {
      try {
        onEvent(build(JSON.parse((message as MessageEvent).data) as never));
      } catch {
        // A frame we can't read is skipped. The next board reload corrects any gap.
      }
    });

  source.onopen = () => onConnection(true);
  source.onerror = () => onConnection(false);
  listen("hello", (d: { you: Person; viewers: Viewer[]; contested: string[] }) => ({
    kind: "hello",
    you: d.you,
    presence: presenceOf(d),
  }));
  listen("presence", (d: { viewers: Viewer[]; contested: string[] }) => ({
    kind: "presence",
    presence: presenceOf(d),
  }));
  for (const kind of ["decision", "state", "comment", "conflict"] as const) {
    listen(kind, (d: object) => ({ kind, ...d }) as LiveEvent);
  }
  listen("resync", () => ({ kind: "resync" }));
  return () => source.close();
}

/** Which finding the caller is looking at, so others can see it. Best effort. */
export function lookAt(contentId: string, findingId: string | null): Promise<Presence> {
  return apiFetch<Presence>(`/collab/content/${contentId}/presence`, {
    method: "POST",
    body: JSON.stringify({ finding_id: findingId }),
  });
}
