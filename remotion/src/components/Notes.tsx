import React, { useMemo } from "react";
import { Easing } from "remotion";
import type { Note, Sky } from "../types";
import { span } from "../kit/camera";
import { HAND_FONT, TITLE_FONT } from "../kit/fonts";
import { onTwos } from "../kit/motion";
import { PALETTES } from "../kit/palettes";
import { DrawFn, PaperCanvas } from "../kit/PaperCanvas";
import { boil, circlePts, paper, Pt, rectPts, rng, PAPER } from "../kit/paper";

const outBack = Easing.out(Easing.back(1.6));

function rotateAbout(ctx: CanvasRenderingContext2D, x: number, y: number, deg: number, s = 1) {
  ctx.translate(x, y);
  ctx.rotate((deg * Math.PI) / 180);
  ctx.scale(s, s);
  ctx.translate(-x, -y);
}

function roundRectPts(x: number, y: number, w: number, h: number, r: number): Pt[] {
  const pts: Pt[] = [];
  const corner = (cx: number, cy: number, a0: number) => {
    for (let i = 0; i <= 6; i++) {
      const a = a0 + (i / 6) * (Math.PI / 2);
      pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
    }
  };
  corner(x + w - r, y + r, -Math.PI / 2);
  corner(x + w - r, y + h - r, 0);
  corner(x + r, y + h - r, Math.PI / 2);
  corner(x + r, y + r, Math.PI);
  return pts;
}

function fitFont(ctx: CanvasRenderingContext2D, text: string, font: (px: number) => string, start: number, maxW: number) {
  let px = start;
  ctx.font = font(px);
  while (px > 24 && ctx.measureText(text).width > maxW) {
    px -= 4;
    ctx.font = font(px);
  }
  return px;
}

const formatCount = (n: number, separator = true) => (separator ? Math.round(n).toLocaleString("en-US") : String(Math.round(n)));

function drawTitle(ctx: CanvasRenderingContext2D, n: Extract<Note, { kind: "title" }>, t: number, b: number, W: number, H: number, sky: Sky) {
  const pal = PALETTES[sky];
  const at = n.at ?? 0.2;
  const e = t - at;
  if (e < 0) return;
  const p = span(e, 0, 0.5, outBack);
  const y = (n.y ?? 0.12) * H - (1 - p) * 420;
  const text = n.text.toUpperCase();
  const px = fitFont(ctx, text, (s) => `700 ${s}px ${TITLE_FONT}`, 96, W * 0.8);
  const tw = ctx.measureText(text).width;
  const bw = tw + 110;
  const bh = px * 1.45;
  ctx.save();
  rotateAbout(ctx, W / 2, y, -2 - (1 - p) * 6);
  paper(ctx, rectPts(W / 2 - bw / 2, y - bh / 2, bw, bh), pal.accent, 9200 + b, { edge: 8, rough: 5, texture: 1 });
  ctx.fillStyle = PAPER;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const wob = (rng(b + 5)() - 0.5) * 2;
  ctx.fillText(text, W / 2, y + px * 0.06 + wob);
  if (n.sub) {
    const se = span(e, 0.35, 0.7, outBack);
    ctx.font = `${Math.round(px * 0.55)}px ${HAND_FONT}`;
    const sw = ctx.measureText(n.sub).width + 70;
    const sh = px * 0.8;
    const sy = y + bh / 2 + sh / 2 + 6;
    ctx.save();
    rotateAbout(ctx, W / 2, sy, 3, Math.max(0.001, se));
    paper(ctx, rectPts(W / 2 - sw / 2, sy - sh / 2, sw, sh), PAPER, 9250 + b, { edge: 0, rough: 4, texture: 0.3 });
    ctx.fillStyle = pal.ink;
    ctx.fillText(n.sub, W / 2, sy + 2 + wob);
    ctx.restore();
  }
  ctx.restore();
}

function drawStamp(ctx: CanvasRenderingContext2D, n: Extract<Note, { kind: "stamp" }>, t: number, b: number, W: number, H: number, sky: Sky) {
  const pal = PALETTES[sky];
  const at = n.at ?? 0.3;
  const e = t - at;
  if (e < 0) return;
  const x = (n.x ?? 0.5) * W;
  const y = (n.y ?? 0.2) * H;
  const size = n.size ?? 1;
  // slam down from above the page, then settle
  const slam = span(e, 0, 0.22, Easing.in(Easing.quad));
  const settle = span(e, 0.22, 0.5, outBack);
  const scale = e < 0.22 ? 1.9 - 0.9 * slam : 1 + 0.06 * (1 - settle);
  let text = n.text;
  if (n.count) {
    const c = n.count;
    const p = span(e, 0.15, 0.15 + (c.dur ?? 1.2), Easing.out(Easing.cubic));
    text = `${c.prefix ?? ""}${formatCount(c.from + (c.to - c.from) * p, c.separator)}${c.suffix ?? ""}`;
  }
  // size the badge for the final text so it doesn't grow while counting
  const finalText = n.count ? `${n.count.prefix ?? ""}${formatCount(n.count.to, n.count.separator)}${n.count.suffix ?? ""}` : text;
  const px = Math.round(88 * size);
  ctx.font = `700 ${px}px ${TITLE_FONT}`;
  const tw = ctx.measureText(finalText).width;
  ctx.save();
  rotateAbout(ctx, x, y, -7 - (1 - slam) * 10, scale);
  ctx.globalAlpha = Math.min(1, e / 0.08);
  if (finalText.length <= 4) {
    const r = Math.max(tw / 2 + 44, 120 * size);
    paper(ctx, circlePts(x, y, r, 40), pal.accent, 9300 + b, { edge: 8, rough: 4, texture: 1 });
  } else {
    const w = tw + 100, h = px * 1.55;
    paper(ctx, roundRectPts(x - w / 2, y - h / 2, w, h, h * 0.32), pal.accent, 9300 + b, { edge: 8, rough: 4, texture: 1 });
  }
  ctx.fillStyle = PAPER;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y + px * 0.06 + (rng(b + 9)() - 0.5) * 2);
  ctx.restore();
}

function drawLabel(ctx: CanvasRenderingContext2D, n: Extract<Note, { kind: "label" }>, t: number, b: number, W: number, H: number, sky: Sky) {
  const pal = PALETTES[sky];
  const at = n.at ?? 0.5;
  const e = t - at;
  if (e < 0) return;
  const tx = n.x * W, ty = n.y * H;
  const px = n.toX * W, py = n.toY * H;
  // the string draws out from the pin, then the tag pops on
  const reach = span(e, 0, 0.35, Easing.out(Easing.quad));
  const pop = span(e, 0.25, 0.6, outBack);
  const r = rng(b + 31);
  ctx.strokeStyle = pal.ink;
  ctx.lineWidth = 4;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(px, py);
  const steps = 14;
  for (let i = 1; i <= Math.ceil(steps * reach); i++) {
    const k = Math.min(i / steps, reach);
    const sag = Math.sin(k * Math.PI) * 26;
    ctx.lineTo(px + (tx - px) * k + (r() - 0.5) * 2, py + (ty - py) * k + sag + (r() - 0.5) * 2);
  }
  ctx.stroke();
  paper(ctx, circlePts(px, py, 11, 14), pal.accent, 9400 + b, { edge: 3, rough: 2, texture: 0 });
  if (pop <= 0) return;
  ctx.font = `58px ${HAND_FONT}`;
  const tw = ctx.measureText(n.text).width;
  const w = tw + 70, h = 92;
  ctx.save();
  rotateAbout(ctx, tx, ty, 3, Math.max(0.001, pop));
  paper(ctx, [[tx - w / 2 + 26, ty - h / 2], [tx + w / 2, ty - h / 2], [tx + w / 2, ty + h / 2], [tx - w / 2 + 26, ty + h / 2], [tx - w / 2, ty]], PAPER, 9450 + b, {
    edge: 0, rough: 4, texture: 0.3,
  });
  ctx.fillStyle = pal.ink;
  ctx.beginPath();
  ctx.arc(tx - w / 2 + 30, ty, 7, 0, Math.PI * 2);
  ctx.fill();
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(n.text, tx + 16, ty + 3 + (r() - 0.5) * 2);
  ctx.restore();
}

// Titles and stamps sit on the screen; labels live in the scene and move with the camera.
export const Notes: React.FC<{ notes: Note[]; sky: Sky; lead: number; space: "screen" | "world" }> = ({ notes, sky, lead, space }) => {
  const draw: DrawFn = useMemo(
    () => (ctx, frame, fps, W, H) => {
      const t = onTwos(frame / fps - lead);
      const b = boil(frame, 3);
      notes.forEach((n, i) => {
        if (n.kind === "title" && space === "screen") drawTitle(ctx, n, t, b + i * 50, W, H, sky);
        if (n.kind === "stamp" && space === "screen") drawStamp(ctx, n, t, b + i * 50, W, H, sky);
        if (n.kind === "label" && space === "world") drawLabel(ctx, n, t, b + i * 50, W, H, sky);
      });
    },
    [notes, sky, lead, space],
  );
  return <PaperCanvas draw={draw} overscan={space === "screen" ? 0 : undefined} />;
};
