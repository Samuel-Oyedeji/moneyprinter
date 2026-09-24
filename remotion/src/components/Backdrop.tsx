import React, { useMemo } from "react";
import type { Backdrop as BackdropSpec, Extra } from "../types";
import { Layer } from "../kit/camera";
import { onTwos } from "../kit/motion";
import { defaultExtras, INTERIORS, PALETTES } from "../kit/palettes";
import {
  birdsDraw,
  bubblesDraw,
  classroomWall,
  earthDraw,
  extraGroundPlanes,
  fishDraw,
  hallWall,
  labWall,
  landmarkDraw,
  lightRays,
  nebula,
  planetDraw,
} from "./scenery";
import type { Ctx, Draw, Plane } from "./scenery";
import type { Landmark } from "../types";
import { DrawFn, OVERSCAN, PaperCanvas } from "../kit/PaperCanvas";
import {
  blobPts,
  boil,
  circlePts,
  hillPts,
  paper,
  paperGroup,
  Pt,
  rayPts,
  rectPts,
  rng,
  shade,
  wavePts,
  PAPER,
} from "../kit/paper";

const M = OVERSCAN;
const L = -M; // left edge of the drawable area

const LANDMARKS: Landmark[] = ["pyramids", "castle", "temple", "lighthouse", "volcano"];

// ------------------------------------------------------------------ skies

function skyPlane(sky: BackdropSpec["sky"], c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const { pal, seed } = c;
    paper(ctx, rectPts(L, L, W + 2 * M, H + 2 * M), pal.sky, seed + 1000 + b, { edge: 0, texture: 1.2, shadow: false });
    if (sky === "room") {
      // striped wallpaper
      for (let x = L + 40; x < W + M; x += 150) {
        paper(ctx, rectPts(x, L, 62, H * 0.62 - L), pal.wallStripe, seed + 1100 + Math.round(x) + b, {
          edge: 0, rough: 3, texture: 0.8, shadow: false, angle: Math.PI / 2,
        });
      }
      return;
    }
    if (sky === "classroom") return classroomWall(c)(ctx, t, b, W, H);
    if (sky === "lab") return labWall(c)(ctx, t, b, W, H);
    if (sky === "hall") return hallWall(c)(ctx, t, b, W, H);
    if (sky === "space") return nebula(c)(ctx, t, b, W, H);
    pal.bands.forEach((band, i) => {
      const y = band.y * H;
      const h = band.h * H;
      const tilt = (rng(seed + i * 13)() - 0.5) * 70;
      const pts: Pt[] = [
        [L, y - tilt / 2],
        [W + M, y + tilt / 2],
        [W + M, y + h + tilt / 2],
        [L, y + h - tilt / 2],
      ];
      paper(ctx, pts, band.c, seed + 2000 + i * 97 + b, { edge: 5, rough: 10, texture: 1 });
    });
    if (sky === "underwater") lightRays(c)(ctx, t, b, W, H);
  };
}

function starsDraw(c: Ctx, everywhere = false): Draw {
  return (ctx, t, b, W, H) => {
    const sr = rng(77 + c.seed);
    for (let i = 0; i < (everywhere ? 80 : 34); i++) {
      const x = L + sr() * (W + 2 * M);
      const y = L + sr() * ((everywhere ? H + M : H * 0.5) - L);
      const ph = sr() * 6;
      const s = 3 + 3 * (0.5 + 0.5 * Math.sin(onTwos(t) * 3 + ph));
      ctx.fillStyle = c.pal.star;
      ctx.beginPath();
      ctx.moveTo(x, y - s * 2);
      ctx.quadraticCurveTo(x, y, x + s * 2, y);
      ctx.quadraticCurveTo(x, y, x, y + s * 2);
      ctx.quadraticCurveTo(x, y, x - s * 2, y);
      ctx.quadraticCurveTo(x, y, x, y - s * 2);
      ctx.fill();
    }
  };
}

function sunDraw(e: Extract<Extra, { type: "sun" }>, c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const sx = (e.x ?? 0.8) * W;
    const sy = (e.y ?? 0.12) * H + Math.sin(onTwos(t) * 1.4) * 6;
    const s = e.size ?? 1;
    const spin = t * 0.12;
    const rays = 12;
    for (let i = 0; i < rays; i++) {
      const a = spin + (i / rays) * Math.PI * 2;
      const len = (150 + (i % 2) * 22 + Math.sin(onTwos(t) * 4 + i) * 5) * s;
      paper(ctx, rayPts(sx, sy, a, 50 * s, len, 44 * s), c.pal.sun, 5000 + i * 31 + b, { edge: 6, rough: 3, angle: a, texture: 1.2 });
    }
    paper(ctx, circlePts(sx, sy, 78 * s), c.pal.sun, 6000 + b, { edge: 7, rough: 3, texture: 1.3 });
    if (e.face) {
      ctx.fillStyle = c.pal.ink;
      for (const ex of [-26, 26]) {
        ctx.beginPath();
        ctx.ellipse(sx + ex * s, sy - 10 * s, 12 * s, 14 * s, 0, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.strokeStyle = c.pal.ink;
      ctx.lineWidth = 5 * s;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.arc(sx, sy + 12 * s, 14 * s, 0.15 * Math.PI, 0.85 * Math.PI);
      ctx.stroke();
    }
  };
}

function moonDraw(e: Extract<Extra, { type: "moon" }>, c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const mx = (e.x ?? 0.2) * W;
    const my = (e.y ?? 0.1) * H;
    const R = 70 * (e.size ?? 1);
    const pts: Pt[] = [];
    for (let a = Math.PI * 0.3; a <= Math.PI * 1.7; a += 0.1) pts.push([mx + Math.cos(a) * R, my + Math.sin(a) * R]);
    for (let a = Math.PI * 1.6; a >= Math.PI * 0.4; a -= 0.1) pts.push([mx + R * 0.42 + Math.cos(a) * R * 0.8, my - R * 0.1 + Math.sin(a) * R * 0.8]);
    paper(ctx, pts, c.pal.moon, 4000 + b, { edge: 5, rough: 3, texture: 0.8 });
  };
}

function cloudsDraw(count: number, c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const r = rng(c.seed + 300);
    for (let i = 0; i < count; i++) {
      const span = W + 2 * M + 500;
      const x0 = r() * span;
      const speed = 8 + r() * 10;
      const x = L - 250 + ((x0 + t * speed) % span);
      const y = H * (0.07 + r() * 0.26);
      const s = 0.8 + r() * 0.6;
      const puffs: Pt[][] = [];
      const n = 4 + Math.floor(r() * 2);
      for (let k = 0; k < n; k++) {
        const px = x + (k - (n - 1) / 2) * 62 * s;
        const py = y - Math.sin((k / (n - 1)) * Math.PI) * 38 * s;
        puffs.push(blobPts(px, py, (48 + r() * 18) * s, c.seed + i * 17 + k, 0.08));
      }
      puffs.push(rectPts(x - (n - 1) * 31 * s, y - 10 * s, (n - 1) * 62 * s, 48 * s));
      paperGroup(ctx, puffs, c.pal.cloud, 3100 + i * 41 + b, { edge: 5, rough: 3, texture: 0.7 });
    }
  };
}

function rainDraw(c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const r = rng(c.seed + 900);
    const tt = onTwos(t);
    const tall = H + 2 * M;
    for (let i = 0; i < 90; i++) {
      const x0 = L + r() * (W + 2 * M + 300);
      const y0 = r() * tall;
      const sp = 1500 + r() * 500;
      const y = L + ((y0 + tt * sp) % tall);
      const x = x0 - (y - L) * 0.18;
      const len = 40 + r() * 30;
      ctx.globalAlpha = 0.55;
      paper(ctx, [[x, y], [x + 5, y], [x + 5 - len * 0.18, y + len], [x - len * 0.18, y + len]], c.pal.rain, 9100 + i + b, {
        edge: 0, rough: 1.5, texture: 0, shadow: false,
      });
      ctx.globalAlpha = 1;
    }
  };
}

function snowDraw(c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const r = rng(c.seed + 950);
    const tt = onTwos(t);
    const tall = H + 2 * M;
    for (let i = 0; i < 70; i++) {
      const x0 = L + r() * (W + 2 * M);
      const y0 = r() * tall;
      const sp = 90 + r() * 70;
      const y = L + ((y0 + tt * sp) % tall);
      const x = x0 + Math.sin(tt * 1.3 + i) * 24;
      paper(ctx, circlePts(x, y, 7 + r() * 7, 12), PAPER, 9500 + i + b, { edge: 0, rough: 3, texture: 0, shadow: false });
    }
  };
}

function windowDraw(e: Extract<Extra, { type: "window" }>, c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const s = e.size ?? 1;
    const w = 300 * s, h = 380 * s;
    const x = (e.x ?? 0.74) * W - w / 2;
    const y = (e.y ?? 0.3) * H - h / 2;
    const day = PALETTES.day;
    paper(ctx, rectPts(x - 26, y - 26, w + 52, h + 52), c.pal.wood, 7600 + b, { edge: 6, rough: 3, texture: 1 });
    paper(ctx, rectPts(x, y, w, h), day.sky, 7610 + b, { edge: 0, rough: 3, texture: 1, shadow: false });
    paperGroup(ctx, [blobPts(x + w * 0.35, y + h * 0.3, 34 * s, 3), blobPts(x + w * 0.52, y + h * 0.26, 42 * s, 4)], day.cloud, 7620 + b, {
      edge: 3, rough: 2, texture: 0.5,
    });
    paper(ctx, hillPts(x, x + w, y + h * 0.82, 16, 5, y + h), day.hills[1], 7630 + b, { edge: 3, rough: 3, texture: 0.8, shadow: false });
    paper(ctx, rectPts(x + w / 2 - 9, y, 18, h), c.pal.wood, 7640 + b, { edge: 3, rough: 2, texture: 0.6 });
    paper(ctx, rectPts(x, y + h * 0.48 - 9, w, 18), c.pal.wood, 7650 + b, { edge: 3, rough: 2, texture: 0.6 });
    paper(ctx, rectPts(x - 44, y + h + 16, w + 88, 26), c.pal.wood, 7660 + b, { edge: 5, rough: 3, texture: 0.8 });
  };
}

function tableDraw(e: Extract<Extra, { type: "table" }>, c: Ctx): Draw {
  return (ctx, t, b, W, H) => {
    const w = (e.width ?? 0.5) * W;
    const x = (e.x ?? 0.62) * W - w / 2;
    const y = (e.y ?? 0.62) * H;
    const legH = H * 0.16;
    paper(ctx, rectPts(x + 30, y + 20, 34, legH), shade(c.pal.wood, -0.06), 7710 + b, { edge: 5, rough: 3, texture: 0.8, angle: Math.PI / 2 });
    paper(ctx, rectPts(x + w - 64, y + 20, 34, legH), shade(c.pal.wood, -0.06), 7720 + b, { edge: 5, rough: 3, texture: 0.8, angle: Math.PI / 2 });
    paper(ctx, rectPts(x, y - 6, w, 40), c.pal.wood, 7730 + b, { edge: 6, rough: 3, texture: 1 });
  };
}

function treeDraw(e: Extract<Extra, { type: "tree" }>, c: Ctx, i: number): Draw {
  return (ctx, t, b, W, H) => {
    const s = e.size ?? 1;
    const x = e.x * W;
    const y = (e.y ?? 0.66) * H;
    const th = 250 * s;
    paper(ctx, [[x - 22 * s, y], [x - 14 * s, y - th], [x + 14 * s, y - th], [x + 22 * s, y]], c.pal.trunk, 7800 + i * 11 + b, {
      edge: 5, rough: 3, texture: 1, angle: Math.PI / 2,
    });
    const sway = Math.sin(onTwos(t) * 1.3 + i) * 4;
    const cy = y - th - 60 * s;
    paperGroup(
      ctx,
      [
        blobPts(x + sway, cy, 110 * s, c.seed + i * 5 + 1),
        blobPts(x - 80 * s + sway, cy + 50 * s, 80 * s, c.seed + i * 5 + 2),
        blobPts(x + 85 * s + sway, cy + 45 * s, 85 * s, c.seed + i * 5 + 3),
      ],
      c.pal.leaf,
      7850 + i * 11 + b,
      { edge: 6, rough: 3, texture: 1.1 },
    );
  };
}

// ------------------------------------------------------------------ grounds

function groundPlanes(ground: string, c: Ctx): Plane[] {
  const { pal, seed } = c;
  const extra = extraGroundPlanes(ground, c);
  if (extra) return extra;
  if (ground === "hills") {
    return [
      { key: "hill-far", depth: 0.35, draw: (ctx, t, b, W, H) => paper(ctx, hillPts(L, W + M, H * 0.52, 70, seed + 1, H + M), pal.hills[0], 7000 + b, { edge: 6, rough: 4, texture: 1 }) },
      { key: "hill-mid", depth: 0.55, draw: (ctx, t, b, W, H) => paper(ctx, hillPts(L, W + M, H * 0.585, 50, seed + 2, H + M), pal.hills[1], 7100 + b, { edge: 6, rough: 4, texture: 1 }) },
      { key: "hill-near", depth: 0.8, draw: (ctx, t, b, W, H) => paper(ctx, hillPts(L, W + M, H * 0.7, 30, seed + 3, H + M), pal.hills[2], 7200 + b, { edge: 6, rough: 4, texture: 1 }) },
    ];
  }
  if (ground === "field") {
    return [
      { key: "field-far", depth: 0.45, draw: (ctx, t, b, W, H) => paper(ctx, hillPts(L, W + M, H * 0.58, 12, seed + 4, H + M), pal.field, 7000 + b, { edge: 6, rough: 4, texture: 1 }) },
      {
        key: "field-near",
        depth: 0.8,
        draw: (ctx, t, b, W, H) => {
          paper(ctx, hillPts(L, W + M, H * 0.76, 10, seed + 5, H + M), shade(pal.field, -0.04), 7100 + b, { edge: 6, rough: 4, texture: 1 });
          const r = rng(seed + 55);
          for (let i = 0; i < 22; i++) {
            const x = L + r() * (W + 2 * M);
            const y = H * (0.6 + r() * 0.12);
            const s = 0.6 + r() * 0.6;
            paper(ctx, [[x - 18 * s, y], [x - 6 * s, y - 36 * s], [x, y - 10 * s], [x + 8 * s, y - 42 * s], [x + 18 * s, y]], pal.grass, 7150 + i + b, {
              edge: 3, rough: 2, texture: 0,
            });
          }
        },
      },
    ];
  }
  if (ground === "sea") {
    const wave = (y: number, amp: number, wl: number, col: string, k: number, depth: number): Plane => ({
      key: `sea-${k}`,
      depth,
      draw: (ctx, t, b, W, H) => {
        const ph = onTwos(t) * (0.9 + k * 0.3) + k * 2;
        paper(ctx, wavePts(L - 40, W + M + 40, H * y + Math.sin(onTwos(t) * 1.1 + k) * 8, amp, wl, ph, H + M), col, 7000 + k * 100 + b, {
          edge: 6, rough: 4, texture: 1,
        });
      },
    });
    return [wave(0.56, 10, 260, pal.sea[0], 0, 0.4), wave(0.64, 16, 320, pal.sea[1], 1, 0.6), wave(0.74, 22, 380, pal.sea[2], 2, 0.85)];
  }
  if (ground === "town") {
    const row = (k: number, depth: number, baseY: number, minH: number, maxH: number, darken: number, windows: boolean): Plane => ({
      key: `town-${k}`,
      depth,
      draw: (ctx, t, b, W, H) => {
        const hr = rng(seed + 99 + k * 7);
        let x = L;
        let i = 0;
        const bottom = H * baseY;
        while (x < W + M) {
          const w = 150 + hr() * 90;
          const h = minH + hr() * (maxH - minH);
          const top = bottom - h;
          const col = shade(pal.houses[(i + k) % pal.houses.length], darken);
          const peak = top - 50 - hr() * 40;
          paper(ctx, [[x, H + M], [x, top], [x + w / 2, peak], [x + w, top], [x + w, H + M]], col, 7300 + k * 500 + i * 13 + b, {
            edge: 5, rough: 3, texture: 0.7,
          });
          if (windows) {
            for (let row = 0; row < 2; row++) {
              for (let cc = 0; cc < 2; cc++) {
                if (hr() < 0.3) continue;
                const wx = x + w * 0.2 + cc * w * 0.38;
                const wy = top + 40 + row * 78;
                paper(ctx, rectPts(wx, wy, 38, 50), pal.windowLit, 7700 + k * 300 + i * 7 + row * 3 + cc + b, {
                  edge: 0, rough: 2, texture: 0.5, shadow: false,
                });
              }
            }
          }
          x += w + 8;
          i++;
        }
      },
    });
    return [
      row(0, 0.35, 0.6, 260, 420, -0.1, false),
      row(1, 0.6, 0.66, 220, 330, 0, true),
      {
        key: "street",
        depth: 0.8,
        draw: (ctx, t, b, W, H) => {
          paper(ctx, hillPts(L, W + M, H * 0.645, 6, seed + 8, H + M), pal.street, 7900 + b, { edge: 6, rough: 4, texture: 0.4 });
          paper(ctx, hillPts(L, W + M, H * 0.8, 5, seed + 9, H + M), shade(pal.street, -0.05), 7950 + b, { edge: 5, rough: 4, texture: 0.3 });
        },
      },
    ];
  }
  return [];
}

function roomFloor(c: Ctx): Plane {
  return {
    key: "floor",
    depth: 0.6,
    draw: (ctx, t, b, W, H) => {
      const { pal } = c;
      paper(ctx, rectPts(L, H * 0.62 - 20, W + 2 * M, 34), shade(pal.wall, -0.12), 7400 + b, { edge: 4, rough: 3, texture: 0.8 });
      paper(ctx, rectPts(L, H * 0.62, W + 2 * M, H * 0.38 + M), pal.floor, 7410 + b, { edge: 6, rough: 3, texture: 1 });
      for (let k = 0; k < 4; k++) {
        const y = H * (0.66 + k * 0.08);
        paper(ctx, rectPts(L, y, W + 2 * M, 18 + k * 6), pal.floorPlank, 7420 + k * 3 + b, { edge: 0, rough: 4, texture: 0.8, shadow: false });
      }
    },
  };
}

// ------------------------------------------------------------------ assembly

export function buildPlanes(spec: BackdropSpec, lead: number): { back: Plane[]; front: Plane[] } {
  const pal = PALETTES[spec.sky];
  const c: Ctx = { pal, seed: spec.seed ?? 1, lead };
  const extras = [...(spec.noDefaults ? [] : defaultExtras(spec.sky)), ...(spec.extras ?? [])];

  const back: Plane[] = [{ key: "sky", depth: 0.08, draw: skyPlane(spec.sky, c) }];
  const front: Plane[] = [];

  extras.forEach((e, i) => {
    const key = `${e.type}-${i}`;
    if (e.type === "stars") back.push({ key, depth: 0.1, draw: starsDraw(c, spec.sky === "space") });
    if (e.type === "planet") back.push({ key, depth: 0.12, draw: planetDraw(e, c) });
    if (e.type === "earth") back.push({ key, depth: 0.12, draw: earthDraw(e, c) });
    if (e.type === "moon") back.push({ key, depth: 0.14, draw: moonDraw(e, c) });
    if (e.type === "sun") back.push({ key, depth: 0.16, draw: sunDraw(e, c) });
    if (e.type === "clouds") back.push({ key, depth: 0.22, draw: cloudsDraw(e.count ?? 3, c) });
    if (e.type === "birds") back.push({ key, depth: 0.25, draw: birdsDraw(e.count ?? 4, c, spec.sky) });
    if (e.type === "window") back.push({ key, depth: 0.12, draw: windowDraw(e, c) });
  });

  if (INTERIORS.includes(spec.sky)) back.push(roomFloor(c));
  else if (spec.sky !== "parchment") {
    const ground = spec.sky === "underwater" ? "seabed" : spec.ground ?? (spec.sky === "space" ? "none" : "hills");
    const planes = groundPlanes(ground, c);
    // landmarks stand behind everything but the far ground layer
    const marks: Plane[] = [];
    extras.forEach((e, i) => {
      if ((LANDMARKS as string[]).includes(e.type)) {
        marks.push({ key: `${e.type}-${i}`, depth: 0.42, draw: landmarkDraw(e as { type: Landmark; x?: number; size?: number }, c) });
      }
    });
    back.push(...planes.slice(0, 1), ...marks, ...planes.slice(1));
  }

  extras.forEach((e, i) => {
    const key = `${e.type}-${i}`;
    if (e.type === "tree") back.push({ key, depth: 0.9, draw: treeDraw(e, c, i) });
    if (e.type === "table") back.push({ key, depth: 1, draw: tableDraw(e, c) });
    if (e.type === "fish") back.push({ key, depth: 0.9, draw: fishDraw(e.count ?? 5, c) });
    if (e.type === "rain") front.push({ key, depth: 1.15, draw: rainDraw(c) });
    if (e.type === "snow") front.push({ key, depth: 1.15, draw: snowDraw(c) });
    if (e.type === "bubbles") front.push({ key, depth: 1.1, draw: bubblesDraw(c) });
  });

  return { back, front };
}

export const Planes: React.FC<{ planes: Plane[]; lead: number; W: number; H: number }> = ({ planes, lead, W, H }) => (
  <>
    {planes.map((p) => (
      <Layer key={p.key} depth={p.depth} W={W} H={H}>
        <PlaneCanvas plane={p} lead={lead} />
      </Layer>
    ))}
  </>
);

const PlaneCanvas: React.FC<{ plane: Plane; lead: number }> = ({ plane, lead }) => {
  const draw: DrawFn = useMemo(
    () => (ctx, frame, fps, W, H) => plane.draw(ctx, frame / fps - lead, boil(frame, 3), W, H),
    [plane, lead],
  );
  return <PaperCanvas draw={draw} />;
};
