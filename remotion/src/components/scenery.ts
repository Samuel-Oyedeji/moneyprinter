import type { Extra, Landmark, Sky } from "../types";
import { onTwos } from "../kit/motion";
import type { Palette } from "../kit/palettes";
import { OVERSCAN } from "../kit/PaperCanvas";
import { blobPts, circlePts, ellipsePts, hillPts, paper, paperGroup, rectPts, rng, shade, wavePts, PAPER } from "../kit/paper";
import type { Pt } from "../kit/paper";
import { capsulePts, roundRectPts } from "../kit/pen";

// The newer settings: interiors (classroom, lab, hall), space, underwater,
// the outdoor grounds added after hills/town/field/sea, landmarks on the
// horizon, and small life (birds, fish, bubbles). Everything is torn paper,
// coloured from the scene's palette so it sits with the rest of the kit.

export type Ctx = { pal: Palette; seed: number; lead: number };
export type Draw = (ctx: CanvasRenderingContext2D, t: number, b: number, W: number, H: number) => void;
export type Plane = { depth: number; draw: Draw; key: string };

const M = OVERSCAN;
const L = -M; // left edge of the drawable area

// A landmark or detail sized from the short side, so it keeps its
// proportions in 9:16 and 16:9 alike.
const unit = (W: number, H: number) => Math.min(W, H);

// ------------------------------------------------------------------ interior walls

export function classroomWall(c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const { pal } = c;
    const bw = Math.min(W * 0.82, H * 1.25);
    const bh = H * 0.28;
    const x = (W - bw) / 2;
    const y = H * 0.09;
    paper(ctx, rectPts(x - 22, y - 22, bw + 44, bh + 44), pal.wood, 7500 + b, { edge: 6, rough: 3, texture: 1 });
    paper(ctx, rectPts(x, y, bw, bh), pal.board, 7510 + b, { edge: 0, rough: 2, texture: 1.3, shadow: false });
    // chalk: a diagram, a triangle and lines of "writing"
    const r = rng(c.seed + 71);
    ctx.save();
    ctx.strokeStyle = "rgba(238,242,232,0.8)";
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = 5;
    const jit = () => (rng(b * 7 + 3)() - 0.5) * 2;
    const cx = x + bw * 0.24;
    const cy = y + bh * 0.5;
    const rr = bh * 0.26;
    ctx.beginPath();
    ctx.arc(cx + jit(), cy, rr, 0, Math.PI * 2);
    ctx.stroke();
    for (let k = 0; k < 4; k++) {
      const a = (k / 4) * Math.PI * 2 + 0.4;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * rr * 1.2, cy + Math.sin(a) * rr * 1.2);
      ctx.lineTo(cx + Math.cos(a) * rr * 1.7, cy + Math.sin(a) * rr * 1.7);
      ctx.stroke();
    }
    const tx = x + bw * 0.5;
    ctx.beginPath();
    ctx.moveTo(tx, y + bh * 0.78);
    ctx.lineTo(tx + bw * 0.12, y + bh * 0.25);
    ctx.lineTo(tx + bw * 0.2, y + bh * 0.78);
    ctx.closePath();
    ctx.stroke();
    for (let line = 0; line < 4; line++) {
      const ly = y + bh * (0.24 + line * 0.18);
      const lx = x + bw * 0.76;
      ctx.beginPath();
      ctx.moveTo(lx, ly);
      for (let k = 1; k <= 8; k++) ctx.lineTo(lx + k * bw * 0.022, ly + Math.sin(k * 2.1 + line) * 6 + (r() - 0.5) * 4);
      ctx.stroke();
    }
    ctx.restore();
    paper(ctx, rectPts(x - 10, y + bh + 18, bw + 20, 22), shade(pal.wood, -0.06), 7520 + b, { edge: 4, rough: 2, texture: 0.8 });
  };
}

export function labWall(c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const { pal } = c;
    // tiles
    ctx.save();
    ctx.globalAlpha = 0.55;
    for (let y = L; y < H * 0.62; y += 96) paper(ctx, rectPts(L, y, W + 2 * M, 6), pal.wallStripe, 7530 + Math.round(y) + b, { edge: 0, rough: 1.5, texture: 0, shadow: false });
    for (let x = L; x < W + M; x += 96) paper(ctx, rectPts(x, L, 6, H * 0.62 - L), pal.wallStripe, 7540 + Math.round(x) + b, { edge: 0, rough: 1.5, texture: 0, shadow: false });
    ctx.restore();
    // a shelf of glassware
    const sy = H * 0.3;
    const x0 = W * 0.08;
    const x1 = W * 0.92;
    paper(ctx, rectPts(x0, sy, x1 - x0, 24), pal.wood, 7550 + b, { edge: 5, rough: 3, texture: 1 });
    const liquids = ["#7fc8a9", "#f2b35b", "#e07a8a", "#8fb8e8", "#b79ce0"];
    const u = unit(W, H) * 0.1;
    const n = Math.max(4, Math.round((x1 - x0) / (u * 1.7)));
    for (let i = 0; i < n; i++) {
      const gx = x0 + (i + 0.5) * ((x1 - x0) / n);
      const col = liquids[i % liquids.length];
      const kind = (i * 7 + c.seed) % 3;
      if (kind === 0) {
        // beaker
        paper(ctx, rectPts(gx - u * 0.35, sy - u * 0.9, u * 0.7, u * 0.9), "#e6f1f3", 7560 + i * 5 + b, { edge: 3, rough: 2, texture: 0.4 });
        paper(ctx, rectPts(gx - u * 0.33, sy - u * 0.45, u * 0.66, u * 0.43), col, 7561 + i * 5 + b, { edge: 0, rough: 2, texture: 0.6, shadow: false });
      } else if (kind === 1) {
        // round flask
        paperGroup(ctx, [circlePts(gx, sy - u * 0.4, u * 0.4, 24), rectPts(gx - u * 0.12, sy - u * 1.15, u * 0.24, u * 0.6)], "#e6f1f3", 7562 + i * 5 + b, { edge: 3, rough: 2, texture: 0.4 });
        paper(ctx, ellipsePts(gx, sy - u * 0.3, u * 0.34, u * 0.24, 20), col, 7563 + i * 5 + b, { edge: 0, rough: 2, texture: 0.6, shadow: false });
      } else {
        // test tubes in a rack
        for (let k = -1; k <= 1; k++) {
          paper(ctx, capsulePts(gx + k * u * 0.26, sy - u * 1.05, gx + k * u * 0.26, sy - u * 0.12, u * 0.18), "#e6f1f3", 7564 + i * 5 + k + b, { edge: 2, rough: 1.5, texture: 0.3 });
          paper(ctx, capsulePts(gx + k * u * 0.26, sy - u * 0.5, gx + k * u * 0.26, sy - u * 0.16, u * 0.13), liquids[(i + k + 5) % 5], 7568 + i * 5 + k + b, { edge: 0, rough: 1.5, texture: 0.3, shadow: false });
        }
        paper(ctx, rectPts(gx - u * 0.45, sy - u * 0.4, u * 0.9, u * 0.1), pal.wood, 7569 + i * 5 + b, { edge: 2, rough: 1.5, texture: 0.6 });
      }
    }
  };
}

export function hallWall(c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const { pal } = c;
    // stone blocks
    const r = rng(c.seed + 404);
    const bh = 86;
    for (let row = 0, y = L; y < H * 0.62; row++, y += bh) {
      for (let x = L - (row % 2) * 90; x < W + M; x += 180) {
        const col = shade(pal.wall, (r() - 0.5) * 0.08);
        paper(ctx, rectPts(x + 4, y + 4, 172, bh - 8), col, 7580 + row * 31 + Math.round(x) + b, { edge: 0, rough: 3, texture: 0.9, shadow: false });
      }
    }
    // banners and torches
    const u = unit(W, H);
    for (const fx of [0.16, 0.84]) {
      const bx = fx * W;
      const w = u * 0.17;
      const top = H * 0.04;
      const len = H * 0.3;
      paper(ctx, [[bx - w / 2, top], [bx + w / 2, top], [bx + w / 2, top + len], [bx, top + len - w * 0.4], [bx - w / 2, top + len]], pal.accent, 7600 + fx * 100 + b, { edge: 5, rough: 3, texture: 1 });
      paper(ctx, rectPts(bx - w * 0.36, top + len * 0.3, w * 0.72, w * 0.72), "#e8b54a", 7601 + fx * 100 + b, { edge: 3, rough: 2, texture: 0.6 });
      paper(ctx, rectPts(bx - w * 0.62, top - 8, w * 1.24, 16), pal.wood, 7602 + fx * 100 + b, { edge: 3, rough: 2, texture: 0.6 });
    }
    for (const fx of [0.36, 0.64]) {
      const tx = fx * W;
      const ty = H * 0.34;
      paper(ctx, [[tx - 14, ty], [tx + 14, ty], [tx + 8, ty + 70], [tx - 8, ty + 70]], pal.wood, 7610 + fx * 100 + b, { edge: 3, rough: 2, texture: 0.6 });
      const fl = 1 + 0.18 * Math.sin(onTwos(t) * 11 + fx * 9);
      paper(ctx, [[tx - 22, ty], [tx + 22, ty], [tx + 6, ty - 70 * fl], [tx, ty - 54 * fl], [tx - 8, ty - 64 * fl]], "#f2a13b", 7611 + fx * 100 + b, { edge: 3, rough: 3, texture: 0.4 });
      paper(ctx, [[tx - 10, ty], [tx + 10, ty], [tx + 2, ty - 38 * fl]], "#fbe07a", 7612 + fx * 100 + b, { edge: 0, rough: 2, texture: 0, shadow: false });
    }
  };
}

// ------------------------------------------------------------------ space and water skies

export function nebula(c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const r = rng(c.seed + 606);
    const cols = ["#3b2a78", "#1f4f7a", "#5a2a6e"];
    ctx.save();
    ctx.globalAlpha = 0.45;
    for (let i = 0; i < 4; i++) {
      const x = L + r() * (W + 2 * M);
      const y = L + r() * (H * 0.8);
      const puffs = [0, 1, 2].map((k) => blobPts(x + (k - 1) * 150, y + (r() - 0.5) * 120, 170 + r() * 90, c.seed + i * 9 + k, 0.2));
      paperGroup(ctx, puffs, cols[i % 3], 7700 + i * 13 + b, { edge: 0, rough: 8, texture: 0.8, shadow: false });
    }
    ctx.restore();
  };
}

export function lightRays(c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const r = rng(c.seed + 707);
    ctx.save();
    ctx.globalAlpha = 0.12;
    for (let i = 0; i < 5; i++) {
      const x = L + r() * (W + 2 * M);
      const sway = Math.sin(onTwos(t) * 0.8 + i) * 40;
      const w = 60 + r() * 90;
      paper(ctx, [[x - w / 2, L], [x + w / 2, L], [x + w * 1.4 + sway + 220, H * 0.75], [x - w * 0.2 + sway + 220, H * 0.75]], "#f6efdc", 7720 + i * 7 + b, {
        edge: 0, rough: 6, texture: 0, shadow: false,
      });
    }
    ctx.restore();
  };
}

// ------------------------------------------------------------------ grounds

const op = { edge: 6, rough: 4, texture: 1 };

function pineRow(x0: number, x1: number, base: number, hMin: number, hMax: number, seed: number): Pt[][] {
  const r = rng(seed);
  const trees: Pt[][] = [];
  for (let x = x0; x < x1; ) {
    const h = hMin + r() * (hMax - hMin);
    const w = h * 0.46;
    trees.push([
      [x, base - h], [x + w * 0.28, base - h * 0.64], [x + w * 0.16, base - h * 0.64], [x + w * 0.4, base - h * 0.32],
      [x + w * 0.24, base - h * 0.32], [x + w * 0.5, base + 4], [x - w * 0.5, base + 4], [x - w * 0.24, base - h * 0.32],
      [x - w * 0.4, base - h * 0.32], [x - w * 0.16, base - h * 0.64], [x - w * 0.28, base - h * 0.64],
    ]);
    x += w * (0.55 + r() * 0.3);
  }
  return trees;
}

function peaks(x0: number, x1: number, lo: number, hi: number, bottom: number, seed: number) {
  const r = rng(seed);
  const pts: Pt[] = [[x0, bottom]];
  const tips: { x: number; y: number; lx: number; ly: number; rx: number; ry: number }[] = [];
  let x = x0;
  let valley = lo + (hi - lo) * 0.2;
  pts.push([x, valley]);
  while (x < x1) {
    const w = 220 + r() * 220;
    const top = hi + r() * (lo - hi) * 0.45;
    const px = x + w * (0.4 + r() * 0.2);
    const nx = x + w;
    const nv = lo - r() * (lo - hi) * 0.35;
    pts.push([px, top], [nx, nv]);
    tips.push({ x: px, y: top, lx: x, ly: valley, rx: nx, ry: nv });
    x = nx;
    valley = nv;
  }
  pts.push([x, bottom]);
  return { pts, tips };
}

export function extraGroundPlanes(ground: string, c: Ctx): Plane[] | null {
  const { pal, seed } = c;
  switch (ground) {
    case "desert":
      return [
        { key: "dune-far", depth: 0.35, draw: (ctx, t, b, W, H) => paper(ctx, wavePts(L, W + M, H * 0.55, 34, 1300, seed, H + M), pal.sand[0], 7000 + b, op) },
        { key: "dune-mid", depth: 0.55, draw: (ctx, t, b, W, H) => paper(ctx, wavePts(L, W + M, H * 0.615, 30, 1000, seed + 2, H + M), pal.sand[1], 7100 + b, op) },
        {
          key: "dune-near",
          depth: 0.8,
          draw: (ctx, t, b, W, H) => {
            paper(ctx, wavePts(L, W + M, H * 0.7, 20, 1500, seed + 4, H + M), pal.sand[2], 7200 + b, op);
            const r = rng(seed + 9);
            for (let i = 0; i < 5; i++) {
              const x = L + r() * (W + 2 * M);
              paper(ctx, blobPts(x, H * (0.74 + r() * 0.1), 18 + r() * 16, seed + i, 0.25, 18), shade(pal.sand[2], -0.15), 7250 + i + b, { edge: 3, rough: 2, texture: 0.6 });
            }
          },
        },
      ];
    case "forest":
      return [
        { key: "forest-back", depth: 0.35, draw: (ctx, t, b, W, H) => {
          paper(ctx, hillPts(L, W + M, H * 0.6, 14, seed + 1, H + M), shade(pal.pine[0], -0.06), 7000 + b, op);
          paperGroup(ctx, pineRow(L, W + M, H * 0.6, H * 0.16, H * 0.24, seed + 3), pal.pine[0], 7010 + b, { edge: 5, rough: 3, texture: 0.9 });
        } },
        { key: "forest-mid", depth: 0.6, draw: (ctx, t, b, W, H) => {
          paperGroup(ctx, pineRow(L + 60, W + M, H * 0.66, H * 0.2, H * 0.3, seed + 5), pal.pine[1], 7100 + b, { edge: 6, rough: 3, texture: 1 });
        } },
        { key: "forest-floor", depth: 0.8, draw: (ctx, t, b, W, H) => {
          paper(ctx, hillPts(L, W + M, H * 0.69, 16, seed + 7, H + M), pal.hills[2], 7200 + b, op);
          const r = rng(seed + 11);
          for (let i = 0; i < 5; i++) {
            const x = L + r() * (W + 2 * M);
            const y = H * (0.69 + r() * 0.03);
            paperGroup(ctx, [blobPts(x, y, 46, seed + i * 3, 0.15), blobPts(x + 50, y + 8, 36, seed + i * 3 + 1, 0.15)], shade(pal.leaf, -0.04), 7250 + i + b, { edge: 4, rough: 3, texture: 0.8 });
          }
        } },
      ];
    case "mountains":
      return [
        { key: "mountains-far", depth: 0.3, draw: (ctx, t, b, W, H) => {
          const m = peaks(L, W + M, H * 0.5, H * 0.28, H + M, seed + 1);
          paper(ctx, m.pts, shade(pal.rock, 0.12), 7000 + b, op);
          m.tips.forEach((p, i) => {
            const f = 0.28;
            paper(ctx, [
              [p.x, p.y], [p.x + (p.rx - p.x) * f, p.y + (p.ry - p.y) * f], [p.x + (p.rx - p.x) * f * 0.5, p.y + (p.ry - p.y) * f * 0.8],
              [p.x, p.y + (p.ry - p.y) * f * 0.95], [p.x + (p.lx - p.x) * f * 0.5, p.y + (p.ly - p.y) * f * 0.75], [p.x + (p.lx - p.x) * f, p.y + (p.ly - p.y) * f],
            ], "#f6f9fc", 7050 + i * 7 + b, { edge: 3, rough: 3, texture: 0.4 });
          });
        } },
        { key: "mountains-mid", depth: 0.5, draw: (ctx, t, b, W, H) => paper(ctx, peaks(L - 80, W + M, H * 0.6, H * 0.46, H + M, seed + 3).pts, pal.rock, 7100 + b, op) },
        { key: "mountains-near", depth: 0.8, draw: (ctx, t, b, W, H) => paper(ctx, hillPts(L, W + M, H * 0.7, 26, seed + 5, H + M), pal.hills[2], 7200 + b, op) },
      ];
    case "city":
      return [
        { key: "city-far", depth: 0.35, draw: (ctx, t, b, W, H) => {
          const r = rng(seed + 21);
          const towers: Pt[][] = [];
          for (let x = L; x < W + M; ) {
            const w = 90 + r() * 110;
            const h = H * (0.16 + r() * 0.22);
            const top = H * 0.62 - h;
            towers.push(r() < 0.3 ? [[x, H + M], [x, top + 40], [x + w * 0.2, top + 40], [x + w * 0.2, top], [x + w * 0.8, top], [x + w * 0.8, top + 40], [x + w, top + 40], [x + w, H + M]] : rectPts(x, top, w, H + M - top));
            if (r() < 0.25) towers.push(rectPts(x + w / 2 - 4, top - 70, 8, 72));
            x += w + 4 + r() * 16;
          }
          paperGroup(ctx, towers, pal.city[0], 7000 + b, { edge: 5, rough: 2, texture: 0.8 });
        } },
        { key: "city-mid", depth: 0.6, draw: (ctx, t, b, W, H) => {
          const r = rng(seed + 23);
          for (let x = L, i = 0; x < W + M; i++) {
            const w = 130 + r() * 110;
            const h = H * (0.12 + r() * 0.16);
            const top = H * 0.66 - h;
            paper(ctx, rectPts(x, top, w, H + M - top), shade(pal.city[1], (r() - 0.5) * 0.06), 7100 + i * 13 + b, { edge: 5, rough: 2, texture: 0.8 });
            ctx.fillStyle = pal.windowLit;
            for (let wy = top + 26; wy < H * 0.64; wy += 44) {
              for (let wx = x + 18; wx < x + w - 26; wx += 34) {
                if (r() < 0.45) continue;
                ctx.globalAlpha = 0.75 + r() * 0.25;
                ctx.fillRect(wx, wy, 16, 22);
              }
            }
            ctx.globalAlpha = 1;
            x += w + 10;
          }
        } },
        { key: "city-street", depth: 0.8, draw: (ctx, t, b, W, H) => {
          paper(ctx, rectPts(L, H * 0.645, W + 2 * M, H * 0.36 + M), "#8a8f96", 7200 + b, { edge: 6, rough: 3, texture: 0.5 });
          paper(ctx, rectPts(L, H * 0.645, W + 2 * M, H * 0.03), "#b3b7bd", 7210 + b, { edge: 4, rough: 2, texture: 0.4 });
          for (let x = L + 40; x < W + M; x += 220) paper(ctx, rectPts(x, H * 0.8, 110, 14), "#f2efe6", 7220 + Math.round(x) + b, { edge: 0, rough: 2, texture: 0, shadow: false });
        } },
      ];
    case "beach":
      return [
        { key: "beach-sea", depth: 0.4, draw: (ctx, t, b, W, H) => {
          paper(ctx, wavePts(L - 40, W + M + 40, H * 0.55 + Math.sin(onTwos(t) * 1.1) * 6, 8, 260, onTwos(t) * 0.9, H + M), pal.sea[0], 7000 + b, op);
          paper(ctx, wavePts(L - 40, W + M + 40, H * 0.6 + Math.sin(onTwos(t) * 1.3 + 1) * 6, 12, 300, onTwos(t) * 1.2 + 2, H + M), pal.sea[1], 7050 + b, op);
        } },
        { key: "beach-sand", depth: 0.75, draw: (ctx, t, b, W, H) => {
          const foam = H * 0.655 + Math.sin(onTwos(t) * 1.6) * 10;
          paper(ctx, wavePts(L - 40, W + M + 40, foam, 7, 180, onTwos(t) * 1.5, H + M), PAPER, 7100 + b, { edge: 0, rough: 4, texture: 0.3, shadow: false });
          paper(ctx, hillPts(L, W + M, H * 0.68, 10, seed + 3, H + M), pal.sand[0], 7150 + b, op);
          paper(ctx, hillPts(L, W + M, H * 0.8, 8, seed + 4, H + M), pal.sand[1], 7160 + b, { ...op, texture: 0.8 });
        } },
      ];
    case "snowfield":
      return [
        { key: "snow-far", depth: 0.35, draw: (ctx, t, b, W, H) => paper(ctx, hillPts(L, W + M, H * 0.52, 70, seed + 1, H + M), pal.snowHills[0], 7000 + b, op) },
        { key: "snow-mid", depth: 0.55, draw: (ctx, t, b, W, H) => {
          paper(ctx, hillPts(L, W + M, H * 0.585, 50, seed + 2, H + M), pal.snowHills[1], 7100 + b, op);
          paperGroup(ctx, pineRow(L + 200, W * 0.35, H * 0.6, H * 0.08, H * 0.12, seed + 8), shade(pal.pine[1], -0.05), 7120 + b, { edge: 4, rough: 2, texture: 0.8 });
        } },
        { key: "snow-near", depth: 0.8, draw: (ctx, t, b, W, H) => paper(ctx, hillPts(L, W + M, H * 0.7, 30, seed + 3, H + M), pal.snowHills[2], 7200 + b, op) },
      ];
    case "lunar":
      return [
        { key: "lunar-far", depth: 0.35, draw: (ctx, t, b, W, H) => paper(ctx, hillPts(L, W + M, H * 0.6, 40, seed + 1, H + M), pal.lunar[0], 7000 + b, op) },
        { key: "lunar-near", depth: 0.8, draw: (ctx, t, b, W, H) => {
          paper(ctx, hillPts(L, W + M, H * 0.68, 14, seed + 2, H + M), pal.lunar[1], 7100 + b, op);
          const r = rng(seed + 13);
          for (let i = 0; i < 6; i++) {
            const x = L + r() * (W + 2 * M);
            const y = H * (0.72 + r() * 0.2);
            const rx = 40 + r() * 80;
            paper(ctx, ellipsePts(x, y, rx, rx * 0.28, 28), pal.lunar[2], 7150 + i * 3 + b, { edge: 4, rough: 2, texture: 0.8 });
            paper(ctx, ellipsePts(x + rx * 0.08, y + rx * 0.06, rx * 0.8, rx * 0.18, 24), shade(pal.lunar[2], -0.08), 7151 + i * 3 + b, { edge: 0, rough: 2, texture: 0.6, shadow: false });
          }
        } },
      ];
    case "seabed":
      return [
        { key: "seabed-rocks", depth: 0.35, draw: (ctx, t, b, W, H) => paper(ctx, hillPts(L, W + M, H * 0.6, 60, seed + 1, H + M), pal.rock, 7000 + b, op) },
        { key: "seabed-mid", depth: 0.55, draw: (ctx, t, b, W, H) => paper(ctx, hillPts(L, W + M, H * 0.66, 16, seed + 2, H + M), pal.sand[0], 7100 + b, op) },
        { key: "seabed-near", depth: 0.8, draw: (ctx, t, b, W, H) => {
          paper(ctx, hillPts(L, W + M, H * 0.71, 12, seed + 3, H + M), pal.sand[1], 7200 + b, op);
          const r = rng(seed + 17);
          const tt = onTwos(t);
          for (let i = 0; i < 6; i++) {
            // seaweed: a strand swaying from its root
            const x = L + 80 + r() * (W + 2 * M - 160);
            const base = H * (0.7 + r() * 0.04);
            const h = H * (0.1 + r() * 0.1);
            const left: Pt[] = [];
            const right: Pt[] = [];
            for (let k = 0; k <= 8; k++) {
              const f = k / 8;
              const sway = Math.sin(tt * 1.6 + i + f * 3) * 26 * f;
              const w = 16 * (1 - f * 0.8);
              left.push([x + sway - w, base - h * f]);
              right.push([x + sway + w, base - h * f]);
            }
            paper(ctx, [...left, ...right.reverse()], i % 2 ? "#4f9a6a" : "#3f8a74", 7250 + i * 5 + b, { edge: 3, rough: 2, texture: 0.6 });
          }
          for (let i = 0; i < 2; i++) {
            // coral
            const x = L + 200 + r() * (W - 200);
            const base = H * 0.73;
            const col = i ? "#f08a7a" : "#f2b35b";
            const s = unit(W, H) * 0.05;
            paperGroup(ctx, [
              capsulePts(x, base, x, base - s * 2.4, s * 0.5),
              capsulePts(x, base - s, x - s * 1.2, base - s * 2.2, s * 0.4),
              capsulePts(x, base - s * 1.4, x + s * 1.1, base - s * 2.6, s * 0.4),
            ], col, 7280 + i * 5 + b, { edge: 3, rough: 2, texture: 0.6 });
          }
        } },
      ];
    default:
      return null;
  }
}

// ------------------------------------------------------------------ landmarks

// Drawn standing on the horizon (y 0.6 of the height), behind the near ground.
export function landmarkDraw(e: { type: Landmark; x?: number; size?: number }, c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const { pal } = c;
    const u = unit(W, H) * (e.size ?? 1);
    const x = (e.x ?? 0.72) * W;
    const base = H * 0.61;
    const o = { edge: 5, rough: 3, texture: 1 };
    switch (e.type) {
      case "pyramids": {
        const pyramid = (px: number, w: number, h: number, k: number) => {
          paper(ctx, [[px, base - h], [px - w / 2, base], [px + w * 0.12, base]], shade(pal.sand[0], 0.05), 7400 + k + b, o);
          paper(ctx, [[px, base - h], [px + w * 0.12, base], [px + w / 2, base]], shade(pal.sand[0], -0.1), 7410 + k + b, o);
        };
        pyramid(x + u * 0.34, u * 0.42, u * 0.24, 1);
        pyramid(x, u * 0.62, u * 0.36, 2);
        break;
      }
      case "castle": {
        const stone = pal.stone;
        const wall = base - u * 0.2;
        const merlons: Pt[][] = [];
        for (let k = -3; k <= 3; k++) merlons.push(rectPts(x + k * u * 0.09 - u * 0.03, wall - u * 0.05, u * 0.06, u * 0.06));
        paperGroup(ctx, [rectPts(x - u * 0.32, wall, u * 0.64, u * 0.2), ...merlons], stone, 7400 + b, o);
        for (const s of [-1, 1]) {
          const tx = x + s * u * 0.3;
          paper(ctx, rectPts(tx - u * 0.07, base - u * 0.36, u * 0.14, u * 0.36), shade(stone, -0.05), 7410 + s + b, o);
          paper(ctx, [[tx - u * 0.09, base - u * 0.36], [tx + u * 0.09, base - u * 0.36], [tx, base - u * 0.5]], pal.roof, 7420 + s + b, o);
        }
        paper(ctx, rectPts(x - u * 0.1, base - u * 0.32, u * 0.2, u * 0.32), shade(stone, 0.04), 7430 + b, o);
        paper(ctx, [[x, base - u * 0.32], [x, base - u * 0.44], [x + u * 0.08, base - u * 0.41], [x + 4, base - u * 0.38]], pal.accent, 7440 + b, { ...o, edge: 3 });
        paper(ctx, roundRectPts(x - u * 0.045, base - u * 0.12, u * 0.09, u * 0.12, u * 0.045), shade(stone, -0.35), 7450 + b, { ...o, edge: 3 });
        break;
      }
      case "temple": {
        const marble = "#efe8da";
        paper(ctx, rectPts(x - u * 0.34, base - u * 0.04, u * 0.68, u * 0.04), shade(marble, -0.06), 7400 + b, o);
        paper(ctx, rectPts(x - u * 0.3, base - u * 0.07, u * 0.6, u * 0.035), shade(marble, -0.03), 7401 + b, o);
        const cols: Pt[][] = [];
        for (let k = 0; k < 6; k++) cols.push(rectPts(x - u * 0.26 + k * u * 0.1, base - u * 0.32, u * 0.05, u * 0.26));
        paperGroup(ctx, cols, marble, 7402 + b, o);
        paper(ctx, rectPts(x - u * 0.31, base - u * 0.37, u * 0.62, u * 0.05), marble, 7403 + b, o);
        paper(ctx, [[x - u * 0.33, base - u * 0.37], [x + u * 0.33, base - u * 0.37], [x, base - u * 0.47]], shade(marble, -0.04), 7404 + b, o);
        break;
      }
      case "lighthouse": {
        const top = base - u * 0.5;
        paper(ctx, blobPts(x, base + u * 0.02, u * 0.14, c.seed + 5, 0.2), pal.rock, 7400 + b, o);
        paper(ctx, [[x - u * 0.08, base], [x - u * 0.05, top], [x + u * 0.05, top], [x + u * 0.08, base]], "#f4efe4", 7401 + b, o);
        for (const f of [0.25, 0.6]) {
          const y0 = base - u * 0.5 * f;
          const w0 = u * (0.08 - 0.03 * f);
          paper(ctx, [[x - w0, y0], [x + w0, y0], [x + w0 * 0.93, y0 - u * 0.07], [x - w0 * 0.93, y0 - u * 0.07]], "#d1495b", 7402 + f * 10 + b, { ...o, edge: 0, shadow: false });
        }
        paper(ctx, rectPts(x - u * 0.045, top - u * 0.06, u * 0.09, u * 0.06), "#fbe07a", 7403 + b, o);
        paper(ctx, [[x - u * 0.06, top - u * 0.06], [x + u * 0.06, top - u * 0.06], [x, top - u * 0.12]], "#2b3a5a", 7404 + b, o);
        // the beam sweeps left and right
        const a = Math.sin(onTwos(t) * 1.4) * 0.9;
        ctx.save();
        ctx.globalAlpha = 0.28;
        const len = u * 1.3;
        paper(ctx, [[x, top - u * 0.03], [x + Math.cos(a) * len, top - u * 0.03 + Math.sin(a) * len * 0.12 - u * 0.1], [x + Math.cos(a) * len, top - u * 0.03 + Math.sin(a) * len * 0.12 + u * 0.1]], "#fbe07a", 7405 + b, { edge: 0, rough: 3, texture: 0, shadow: false });
        ctx.restore();
        break;
      }
      case "volcano": {
        const w = u * 0.9;
        const h = u * 0.42;
        paper(ctx, [[x - w / 2, base], [x - w * 0.1, base - h], [x + w * 0.1, base - h], [x + w / 2, base]], shade(pal.rock, -0.08), 7400 + b, o);
        paper(ctx, [[x - w * 0.1, base - h], [x - w * 0.02, base - h * 0.78], [x + w * 0.03, base - h * 0.88], [x + w * 0.1, base - h]], "#f06b3f", 7401 + b, { ...o, edge: 3 });
        const tt = onTwos(t);
        ctx.save();
        for (let k = 0; k < 5; k++) {
          const life = (tt * 0.35 + k / 5) % 1;
          ctx.globalAlpha = 0.7 * (1 - life);
          const r0 = u * (0.05 + 0.1 * life);
          paper(ctx, blobPts(x + Math.sin(k * 2.3) * u * 0.05 + life * u * 0.12, base - h - life * u * 0.5, r0, c.seed + k, 0.15, 20), "#7d7a80", 7410 + k + b, {
            edge: 0, rough: 3, texture: 0.4, shadow: false,
          });
        }
        ctx.restore();
        break;
      }
    }
  };
}

// ------------------------------------------------------------------ sky objects and life

export function planetDraw(e: Extract<Extra, { type: "planet" }>, c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const x = (e.x ?? 0.76) * W;
    const y = (e.y ?? 0.2) * H + Math.sin(onTwos(t) * 0.9) * 5;
    const r = 110 * (e.size ?? 1);
    const col = e.color ?? "#e0a36a";
    const tilt = -0.32;
    const ring = (front: boolean) => {
      const outer = ellipsePts(0, 0, r * 1.9, r * 0.5, 48);
      const inner = ellipsePts(0, 0, r * 1.45, r * 0.32, 48).reverse();
      const rot = (pts: Pt[]) => pts.map(([px, py]) => [x + px * Math.cos(tilt) - py * Math.sin(tilt), y + px * Math.sin(tilt) + py * Math.cos(tilt)] as Pt);
      ctx.save();
      if (front) {
        // only the half of the ring that passes in front of the planet
        ctx.beginPath();
        ctx.moveTo(x - Math.cos(tilt) * r * 3, y - Math.sin(tilt) * r * 3);
        ctx.lineTo(x + Math.cos(tilt) * r * 3, y + Math.sin(tilt) * r * 3);
        ctx.lineTo(x + Math.cos(tilt) * r * 3 - Math.sin(tilt) * r * 3, y + Math.sin(tilt) * r * 3 + Math.cos(tilt) * r * 3);
        ctx.lineTo(x - Math.cos(tilt) * r * 3 - Math.sin(tilt) * r * 3, y - Math.sin(tilt) * r * 3 + Math.cos(tilt) * r * 3);
        ctx.clip();
      }
      paper(ctx, [...rot(outer), ...rot(inner)], "#f1d9a8", 4200 + (front ? 1 : 0) + b, { edge: 3, rough: 2, texture: 0.6, shadow: !front });
      ctx.restore();
    };
    ring(false);
    paper(ctx, circlePts(x, y, r, 40), col, 4210 + b, { edge: 5, rough: 3, texture: 1.1 });
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.clip();
    for (const [dy, w] of [[-0.35, 0.12], [0.15, 0.16]]) {
      paper(ctx, rectPts(x - r * 1.2, y + dy * r, r * 2.4, w * r), shade(col, -0.1), 4220 + dy * 10 + b, { edge: 0, rough: 3, texture: 0.8, shadow: false });
    }
    ctx.restore();
    ring(true);
  };
}

export function earthDraw(e: Extract<Extra, { type: "earth" }>, c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const x = (e.x ?? 0.72) * W;
    const y = (e.y ?? 0.24) * H;
    const r = 130 * (e.size ?? 1);
    paper(ctx, circlePts(x, y, r, 44), "#4f8fd1", 4300 + b, { edge: 5, rough: 3, texture: 1 });
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.clip();
    const drift = onTwos(t) * 6;
    const land: Pt[][] = [
      blobPts(x - r * 0.35 + drift, y - r * 0.25, r * 0.38, 11, 0.3),
      blobPts(x + r * 0.4 + drift, y + r * 0.2, r * 0.3, 12, 0.3),
      blobPts(x - r * 0.1 + drift, y + r * 0.55, r * 0.22, 13, 0.3),
    ];
    paperGroup(ctx, land, "#6fb56a", 4310 + b, { edge: 3, rough: 3, texture: 0.8 });
    ctx.globalAlpha = 0.85;
    paper(ctx, capsulePts(x - r * 0.7 + drift * 1.5, y - r * 0.55, x + r * 0.1 + drift * 1.5, y - r * 0.45, r * 0.12), "#fbf6ea", 4320 + b, { edge: 0, rough: 2, texture: 0.3, shadow: false });
    ctx.globalAlpha = 0.25;
    paper(ctx, circlePts(x + r * 0.35, y + r * 0.2, r * 1.0, 40), "#10133a", 4330 + b, { edge: 0, rough: 2, texture: 0, shadow: false });
    ctx.restore();
  };
}

export function birdsDraw(count: number, c: Ctx, sky: Sky): Draw {
  return (ctx, t, b, W, H) => {
    const r = rng(c.seed + 808);
    const tt = onTwos(t);
    const col = sky === "night" ? "#0f1133" : shade(c.pal.ink, 0.08);
    for (let i = 0; i < count; i++) {
      const span = W + 2 * M + 400;
      const x = L - 200 + ((r() * span + tt * (70 + r() * 40)) % span);
      const y = H * (0.1 + r() * 0.2) + Math.sin(tt * 2 + i) * 10;
      const s = 16 + r() * 10;
      const flap = Math.sin(tt * 9 + i * 1.7);
      const tip = -s * 0.9 * flap;
      paper(ctx, [[x - s * 1.4, y + tip], [x - s * 0.5, y - s * 0.2 + tip * 0.3], [x, y + s * 0.25], [x + s * 0.5, y - s * 0.2 + tip * 0.3], [x + s * 1.4, y + tip], [x + s * 0.3, y + s * 0.2], [x, y + s * 0.5], [x - s * 0.3, y + s * 0.2]], col, 4400 + i + b, {
        edge: 2, rough: 1.2, texture: 0, shadow: false,
      });
    }
  };
}

export function fishDraw(count: number, c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const r = rng(c.seed + 909);
    const tt = onTwos(t);
    const cols = ["#f2b35b", "#f08a7a", "#8fd0c8", "#f6d56a"];
    for (let i = 0; i < count; i++) {
      const dir = r() < 0.6 ? 1 : -1;
      const span = W + 2 * M + 300;
      const x = dir > 0 ? L - 150 + ((r() * span + tt * (60 + r() * 50)) % span) : W + M + 150 - ((r() * span + tt * (60 + r() * 50)) % span);
      const y = H * (0.18 + r() * 0.4) + Math.sin(tt * 1.5 + i) * 14;
      const s = 26 + r() * 18;
      const wag = Math.sin(tt * 10 + i) * 0.35;
      const col = cols[i % cols.length];
      const body = ellipsePts(x, y, s, s * 0.52, 22);
      const tx = x - dir * s * 0.9;
      const tail: Pt[] = [[tx, y], [tx - dir * s * 0.7, y - s * (0.5 + wag)], [tx - dir * s * 0.7, y + s * (0.5 - wag)]];
      paperGroup(ctx, [body, tail], col, 4500 + i * 3 + b, { edge: 3, rough: 1.5, texture: 0.6 });
      ctx.fillStyle = "#1c1f3a";
      ctx.beginPath();
      ctx.arc(x + dir * s * 0.5, y - s * 0.1, s * 0.09, 0, Math.PI * 2);
      ctx.fill();
    }
  };
}

export function bubblesDraw(c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const r = rng(c.seed + 1001);
    const tt = onTwos(t);
    const tall = H + 2 * M;
    ctx.save();
    for (let i = 0; i < 26; i++) {
      const x0 = L + r() * (W + 2 * M);
      const sp = 60 + r() * 90;
      const y = H + M - ((r() * tall + tt * sp) % tall);
      const x = x0 + Math.sin(tt * 2 + i) * 12;
      const rad = 6 + r() * 14;
      ctx.globalAlpha = 0.5;
      ctx.strokeStyle = "#e8f6fb";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(x, y, rad, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 0.6;
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(x - rad * 0.35, y - rad * 0.35, rad * 0.22, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  };
}
