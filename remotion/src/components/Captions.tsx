import React, { useMemo } from "react";
import { Easing } from "remotion";
import type { Word } from "../types";
import { Chunk, chunkWords } from "../kit/chunks";
import { span } from "../kit/camera";
import { HAND_FONT } from "../kit/fonts";
import { DrawFn, PaperCanvas } from "../kit/PaperCanvas";
import { boil, paper, rectPts, rng, PAPER } from "../kit/paper";

// Captions: one short phrase at a time on a torn cream strip. Upcoming
// words wait faintly, spoken words turn to ink, and the word being said is
// in the accent colour. Vertical video keeps them in the lower third, clear
// of the Shorts/TikTok buttons below; landscape puts them near the bottom.

type CaptionLayout = { fontPx: number; lineH: number; maxW: number; centerY: number };

export function captionLayout(W: number, H: number): CaptionLayout {
  if (W > H) return { fontPx: 62, lineH: 74, maxW: Math.min(1300, W * 0.72), centerY: 0.885 };
  return { fontPx: 70, lineH: 84, maxW: Math.min(820, W * 0.78), centerY: 0.765 };
}

type Laid = { text: string; x: number; y: number; at: number; end: number }[];

function layout(ctx: CanvasRenderingContext2D, c: Chunk, W: number, H: number): { words: Laid; box: { x: number; y: number; w: number; h: number } } {
  const { fontPx: FONT_PX, lineH: LINE_H, maxW: MAX_W, centerY: CENTER_Y } = captionLayout(W, H);
  ctx.font = `${FONT_PX}px ${HAND_FONT}`;
  const space = ctx.measureText(" ").width;
  const lines: { words: Word[]; w: number }[] = [{ words: [], w: 0 }];
  for (const w of c.words) {
    const ww = ctx.measureText(w.text).width;
    const line = lines[lines.length - 1];
    const add = line.words.length ? space + ww : ww;
    if (line.w + add > MAX_W && line.words.length) lines.push({ words: [w], w: ww });
    else {
      line.words.push(w);
      line.w += add;
    }
  }
  const cy = CENTER_Y * H;
  const top = cy - (lines.length * LINE_H) / 2;
  const laid: Laid = [];
  let maxW = 0;
  lines.forEach((line, li) => {
    let x = W / 2 - line.w / 2;
    maxW = Math.max(maxW, line.w);
    for (const w of line.words) {
      laid.push({ text: w.text, x, y: top + li * LINE_H + LINE_H / 2, at: w.at, end: w.end ?? w.at + 0.4 });
      x += ctx.measureText(w.text).width + space;
    }
  });
  const padX = 44, padY = 20;
  return { words: laid, box: { x: W / 2 - maxW / 2 - padX, y: top - padY, w: maxW + padX * 2, h: lines.length * LINE_H + padY * 2 } };
}

export const Captions: React.FC<{ words: Word[]; ink: string; accent: string }> = ({ words, ink, accent }) => {
  const chunks = useMemo(() => chunkWords(words), [words]);
  const draw: DrawFn = useMemo(
    () => (ctx, frame, fps, W, H) => {
      const t = frame / fps;
      const idx = chunks.findIndex((c) => t >= c.start && t < c.end);
      if (idx < 0) return;
      const c = chunks[idx];
      const b = boil(frame, 3);
      const { words: laid, box } = layout(ctx, c, W, H);
      const pop = span(t - c.start, 0, 0.14, Easing.out(Easing.back(2)));
      const tilt = (rng(idx * 17 + 3)() - 0.5) * 2.4;
      ctx.save();
      ctx.translate(W / 2, box.y + box.h / 2);
      ctx.rotate((tilt * Math.PI) / 180);
      ctx.scale(0.9 + 0.1 * pop, 0.9 + 0.1 * pop);
      ctx.translate(-W / 2, -(box.y + box.h / 2));
      paper(ctx, rectPts(box.x, box.y, box.w, box.h), PAPER, 9600 + idx * 7 + b, { edge: 0, rough: 6, texture: 0.35 });
      ctx.font = `${captionLayout(W, H).fontPx}px ${HAND_FONT}`;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      const wob = rng(b + 77);
      // the word being spoken right now (the last one that has started)
      let active = -1;
      laid.forEach((w, i) => {
        if (t >= w.at) active = i;
      });
      laid.forEach((w, i) => {
        const spoken = t >= w.at - 0.02;
        const isActive = i === active && t < w.end + 0.15;
        const rise = isActive ? span(t - w.at, 0, 0.1) * -4 : 0;
        ctx.globalAlpha = spoken ? 1 : 0.28;
        ctx.fillStyle = isActive ? accent : ink;
        ctx.fillText(w.text, w.x, w.y + 4 + rise + (wob() - 0.5) * 2);
      });
      ctx.globalAlpha = 1;
      ctx.restore();
    },
    [chunks, ink, accent],
  );
  return <PaperCanvas draw={draw} overscan={0} />;
};
