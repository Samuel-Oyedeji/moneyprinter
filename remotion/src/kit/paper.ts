// Paper cut-out drawing kit.
// Every function takes a seed, so the same frame always draws the same way.

export type Pt = [number, number];

export const PAPER = "#f6efdc"; // cream edge colour of torn paper
export const SHADOW = "rgba(10,10,40,0.22)";

// Seeded random number generator (mulberry32).
export function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Stop-motion "boil": the seed changes every `hold` frames.
export const boil = (frame: number, hold = 3) => Math.floor(frame / hold);

// ---------- shapes as point lists ----------

export function circlePts(cx: number, cy: number, r: number, n = 48): Pt[] {
  return ellipsePts(cx, cy, r, r, n);
}

export function ellipsePts(cx: number, cy: number, rx: number, ry: number, n = 48): Pt[] {
  const pts: Pt[] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    pts.push([cx + Math.cos(a) * rx, cy + Math.sin(a) * ry]);
  }
  return pts;
}

export function rectPts(x: number, y: number, w: number, h: number): Pt[] {
  return [
    [x, y],
    [x + w, y],
    [x + w, y + h],
    [x, y + h],
  ];
}

// A lumpy round blob: bushes, cloud puffs, tree tops.
export function blobPts(cx: number, cy: number, r: number, seed: number, lump = 0.12, n = 36): Pt[] {
  const rr = rng(seed);
  const k1 = rr() * 6, k2 = rr() * 6;
  const pts: Pt[] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    const d = r * (1 + lump * Math.sin(a * 3 + k1) + lump * 0.6 * Math.sin(a * 5 + k2));
    pts.push([cx + Math.cos(a) * d, cy + Math.sin(a) * d]);
  }
  return pts;
}

// A rolling hill line from x0 to x1 around `y`, closed down to `bottom`.
export function hillPts(x0: number, x1: number, y: number, amp: number, seed: number, bottom: number): Pt[] {
  const rr = rng(seed);
  const f1 = 0.002 + rr() * 0.002, f2 = 0.005 + rr() * 0.003;
  const p1 = rr() * 6, p2 = rr() * 6;
  const pts: Pt[] = [];
  for (let x = x0; x <= x1; x += 24) {
    pts.push([x, y - amp * (0.65 * Math.sin(x * f1 + p1) + 0.35 * Math.sin(x * f2 + p2))]);
  }
  pts.push([x1, bottom], [x0, bottom]);
  return pts;
}

// A wavy strip top edge (sea), closed down to `bottom`.
export function wavePts(x0: number, x1: number, y: number, amp: number, wavelength: number, phase: number, bottom: number): Pt[] {
  const pts: Pt[] = [];
  for (let x = x0; x <= x1; x += 16) {
    pts.push([x, y + amp * Math.sin((x / wavelength) * Math.PI * 2 + phase)]);
  }
  pts.push([x1, bottom], [x0, bottom]);
  return pts;
}

// A rounded ray (like the sun's arms), pointing at `angle`.
export function rayPts(cx: number, cy: number, angle: number, inner: number, outer: number, width: number): Pt[] {
  const pts: Pt[] = [];
  const n = 10;
  const ca = Math.cos(angle);
  const sa = Math.sin(angle);
  const px = -sa;
  const py = ca;
  const len = outer - inner;
  // one side, the round tip, then the other side
  for (let i = 0; i <= n; i++) {
    const d = inner + (len - width / 2) * (i / n);
    const w = (width / 2) * (1 - 0.15 * (i / n));
    pts.push([cx + ca * d + px * w, cy + sa * d + py * w]);
  }
  for (let i = 1; i < n; i++) {
    const a = Math.PI / 2 - (i / n) * Math.PI;
    const tip = inner + len - width / 2;
    const w = (width / 2) * 0.85;
    pts.push([cx + ca * (tip + Math.cos(a) * w) + px * Math.sin(a) * w, cy + sa * (tip + Math.cos(a) * w) + py * Math.sin(a) * w]);
  }
  for (let i = n; i >= 0; i--) {
    const d = inner + (len - width / 2) * (i / n);
    const w = (width / 2) * (1 - 0.15 * (i / n));
    pts.push([cx + ca * d - px * w, cy + sa * d - py * w]);
  }
  return pts;
}

// ---------- rough paths ----------

// Split each edge into small steps and push each point a random amount.
// `amp` = how rough; `step` = spacing of the tear teeth.
export function roughPath(ctx: CanvasRenderingContext2D, pts: Pt[], r: () => number, amp: number, step = 6, newPath = true) {
  if (newPath) ctx.beginPath();
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % pts.length];
    const len = Math.hypot(x1 - x0, y1 - y0);
    const n = Math.max(1, Math.floor(len / step));
    for (let j = 0; j < n; j++) {
      const t = j / n;
      const x = x0 + (x1 - x0) * t + (r() - 0.5) * amp;
      const y = y0 + (y1 - y0) * t + (r() - 0.5) * amp;
      if (i === 0 && j === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
  }
  ctx.closePath();
}

// ---------- brush texture ----------

// Lighten (amt > 0) or darken a "#rrggbb" colour. Returns hex too, so shades
// can be passed anywhere a colour goes (brush strokes shade it again).
export function shade(hex: string, amt: number) {
  const n = parseInt(hex.slice(1, 7), 16);
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v + amt * 255)));
  const out = (c((n >> 16) & 255) << 16) | (c((n >> 8) & 255) << 8) | c(n & 255);
  return `#${out.toString(16).padStart(6, "0")}`;
}

function bounds(pts: Pt[]) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of pts) {
    x0 = Math.min(x0, x); y0 = Math.min(y0, y);
    x1 = Math.max(x1, x); y1 = Math.max(y1, y);
  }
  return { x0, y0, x1, y1 };
}

// Short semi-transparent strokes, clipped to the current path.
export function brushStrokes(
  ctx: CanvasRenderingContext2D,
  pts: Pt[],
  color: string,
  r: () => number,
  opts: { angle?: number; density?: number; size?: number } = {},
) {
  const { angle = 0, density = 1, size = 1 } = opts;
  const b = bounds(pts);
  const area = (b.x1 - b.x0) * (b.y1 - b.y0);
  const count = Math.min(1400, Math.floor((area / 900) * density));
  ctx.lineCap = "round";
  for (let i = 0; i < count; i++) {
    const x = b.x0 + r() * (b.x1 - b.x0);
    const y = b.y0 + r() * (b.y1 - b.y0);
    const len = (14 + r() * 38) * size;
    const a = angle + (r() - 0.5) * 0.35;
    ctx.strokeStyle = shade(color, (r() - 0.5) * 0.12);
    ctx.globalAlpha = 0.18 + r() * 0.25;
    ctx.lineWidth = (3 + r() * 6) * size;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + Math.cos(a) * len, y + Math.sin(a) * len);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

// ---------- the main call ----------

export type PaperOpts = {
  edge?: number; // width of the cream torn border (0 = none)
  rough?: number; // roughness of the colour edge
  angle?: number; // brush stroke direction
  texture?: number; // brush density (0 = flat)
  shadow?: boolean;
  brush?: number; // brush stroke size (1 = scenery; smaller for faces and props)
  lift?: number; // how far the shadow falls (1 = scenery)
};

// Draw one torn-paper shape: shadow, cream edge, colour, brush texture.
export function paper(ctx: CanvasRenderingContext2D, pts: Pt[], color: string, seed: number, o: PaperOpts = {}) {
  paperGroup(ctx, [pts], color, seed, o);
}

// Several shapes cut from one sheet (a cloud from puffs, a tree top from
// blobs): all the shadows, then all the cream edges, then all the colour,
// so no cream line shows where the pieces overlap.
export function paperGroup(ctx: CanvasRenderingContext2D, shapes: Pt[][], color: string, seed: number, o: PaperOpts = {}) {
  const { edge = 7, rough = 4, angle = 0, texture = 1, shadow = true, brush = 1, lift = 1 } = o;
  const r = rng(seed);
  // Each pass replays the same random stream per shape so edges line up.
  const seeds = shapes.map(() => Math.floor(r() * 1e9));

  if (shadow) {
    ctx.save();
    ctx.translate(4 * lift, 6 * lift);
    ctx.beginPath();
    shapes.forEach((pts, i) => roughPath(ctx, pts, rng(seeds[i] + 1), rough + edge, 5, false));
    ctx.fillStyle = SHADOW;
    ctx.fill();
    ctx.restore();
  }

  if (edge > 0) {
    // cream layer: draw the outline with a thick, torn stroke
    ctx.beginPath();
    shapes.forEach((pts, i) => roughPath(ctx, pts, rng(seeds[i] + 2), edge * 1.6, 4, false));
    ctx.fillStyle = PAPER;
    ctx.fill();
    ctx.lineWidth = edge * 1.6;
    ctx.lineJoin = "round";
    ctx.strokeStyle = PAPER;
    ctx.stroke();
  }

  ctx.beginPath();
  shapes.forEach((pts, i) => roughPath(ctx, pts, rng(seeds[i] + 3), rough, 6, false));
  ctx.fillStyle = color;
  ctx.fill();

  if (texture > 0) {
    ctx.save();
    ctx.clip();
    const all = shapes.flat();
    brushStrokes(ctx, all, color, rng(seeds[0] + 4), { angle, density: texture / (brush * brush), size: brush });
    ctx.restore();
  }
}
