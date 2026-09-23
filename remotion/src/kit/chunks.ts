import type { Word } from "../types";

// Caption phrasing: which words share the caption strip at a time.

export type Chunk = { words: Word[]; start: number; end: number };

const TARGET_CHARS = 26; // about one comfortable line

const textLen = (ws: Word[]) => ws.map((w) => w.text).join(" ").length;
const capital = (w?: Word) => !!w && /^[A-Z]/.test(w.text);

// Cut one clause into phrases near TARGET_CHARS long: the cheapest set of
// break points, where a lone word or a split name costs extra.
function splitClause(clause: Word[]): Word[][] {
  const n = clause.length;
  const best = new Array<number>(n + 1).fill(Infinity);
  const from = new Array<number>(n + 1).fill(0);
  best[0] = 0;
  for (let j = 1; j <= n; j++) {
    for (let i = 0; i < j; i++) {
      const len = textLen(clause.slice(i, j));
      if (len > 44 && j - i > 1) continue;
      let cost = (len - TARGET_CHARS) ** 2;
      if (j - i === 1 && n > 1) cost += 300;
      if (j < n && capital(clause[j]) && capital(clause[j - 1])) cost += 5000;
      if (best[i] + cost < best[j]) {
        best[j] = best[i] + cost;
        from[j] = i;
      }
    }
  }
  const pieces: Word[][] = [];
  for (let j = n; j > 0; j = from[j]) pieces.unshift(clause.slice(from[j], j));
  return pieces;
}

// Phrases break at punctuation, then long clauses are split evenly.
export function chunkWords(words: Word[]): Chunk[] {
  const clauses: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    cur.push(w);
    if (/[.!?…,;:—]["”']?$/.test(w.text)) {
      clauses.push(cur);
      cur = [];
    }
  }
  if (cur.length) clauses.push(cur);

  // a tiny lead-in ("But,") joins the clause after it when they fit together
  const merged: Word[][] = [];
  for (let i = 0; i < clauses.length; i++) {
    const c = clauses[i];
    const next = clauses[i + 1];
    const sentenceEnd = /[.!?…]["”']?$/.test(c[c.length - 1].text);
    if (next && !sentenceEnd && c.length <= 2 && textLen([...c, ...next]) <= TARGET_CHARS + 6) {
      clauses[i + 1] = [...c, ...next];
    } else merged.push(c);
  }

  const chunks: Chunk[] = [];
  for (const clause of merged) {
    for (const piece of splitClause(clause)) chunks.push({ words: piece, start: piece[0].at, end: 0 });
  }

  chunks.forEach((c, i) => {
    const last = c.words[c.words.length - 1];
    const own = (last.end ?? last.at + 0.45) + 0.35;
    const next = chunks[i + 1]?.start ?? Infinity;
    c.start -= 0.08;
    c.end = Math.min(own, next - 0.08);
  });
  return chunks;
}
