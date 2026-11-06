import { wordDiff } from "@/lib/wordDiff";

/** Shows the difference between two texts as struck-out and underlined words. */
export function TrackedChanges({
  before,
  after,
}: {
  before: string;
  after: string;
}) {
  return (
    <p className="rounded-md bg-muted p-2 leading-relaxed whitespace-pre-wrap">
      {wordDiff(before, after).map((part, index) => {
        if (part.kind === "removed") {
          return (
            <del
              key={index}
              className="text-foreground line-through decoration-destructive decoration-2"
            >
              <span className="sr-only">Removed: </span>
              {part.text}
            </del>
          );
        }
        if (part.kind === "added") {
          return (
            <ins key={index} className="font-medium text-foreground underline">
              <span className="sr-only">Added: </span>
              {part.text}
            </ins>
          );
        }
        return part.text;
      })}
    </p>
  );
}
