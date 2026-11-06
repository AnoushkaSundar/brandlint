export type DiffPart = {
  kind: "same" | "removed" | "added";
  text: string;
};

function tokens(text: string): string[] {
  return text.split(/(\s+)/).filter(Boolean);
}

/** Compares two strings word by word, using a longest-common-subsequence table. */
export function wordDiff(before: string, after: string): DiffPart[] {
  const old = tokens(before);
  const next = tokens(after);
  const table = Array.from({ length: old.length + 1 }, () =>
    new Array<number>(next.length + 1).fill(0),
  );

  for (let i = old.length - 1; i >= 0; i -= 1) {
    for (let j = next.length - 1; j >= 0; j -= 1) {
      table[i][j] =
        old[i] === next[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  const parts: DiffPart[] = [];
  const push = (kind: DiffPart["kind"], text: string) => {
    const last = parts.at(-1);
    if (last?.kind === kind) last.text += text;
    else parts.push({ kind, text });
  };

  let i = 0;
  let j = 0;
  while (i < old.length || j < next.length) {
    if (i < old.length && j < next.length && old[i] === next[j]) {
      push("same", old[i]);
      i += 1;
      j += 1;
    } else if (
      i < old.length &&
      (j === next.length || table[i + 1][j] >= table[i][j + 1])
    ) {
      push("removed", old[i]);
      i += 1;
    } else {
      push("added", next[j]);
      j += 1;
    }
  }
  return parts;
}
