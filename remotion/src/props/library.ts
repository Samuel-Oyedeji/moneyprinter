import type { PropName, Shape } from "../types";
import { HAND_FONT, TITLE_FONT } from "../kit/fonts";
import { capsulePts, ell, Pen } from "../kit/pen";
import { PAPER, Pt, rng, shade } from "../kit/paper";

// Every prop is drawn in code from paper shapes, inside a box whose
// bottom-centre sits at the origin. `aspect` is the box's width / height;
// `held` is its default size when a person carries it (fraction of the
// person's height).

export type PropOpts = {
  color?: string;
  color2?: string;
  text?: string;
  mould?: boolean;
  shapes?: Shape[];
  t: number; // scene time (on twos), for props that animate
};

type PropDef = { aspect: number; held: number; draw: (p: Pen, o: PropOpts) => void };

const INK = "#2b2230";
const GOLD = "#f2c14e";
const GOLD_DK = "#d9a23a";
const WOOD = "#8a5a3c";
const GLASS = "#d5e8ee";
const SILVER = "#c9d2dc";
const hex = (c: string) => (c.startsWith("#") ? c : "#888888");
const dk = (c: string, a = 0.1) => shade(hex(c), -a);
const lt = (c: string, a = 0.1) => shade(hex(c), a);

// a handle or curve made of short sticks, so it keeps the torn-paper edge
function arc(p: Pen, cx: number, cy: number, rx: number, ry: number, a0: number, a1: number, width: number, color: string) {
  const n = 7;
  const segs: Pt[][] = [];
  for (let i = 0; i < n; i++) {
    const t0 = a0 + ((a1 - a0) * i) / n;
    const t1 = a0 + ((a1 - a0) * (i + 1)) / n;
    segs.push(capsulePts(p.X(cx + Math.cos(t0) * rx), p.Y(cy + Math.sin(t0) * ry), p.X(cx + Math.cos(t1) * rx), p.Y(cy + Math.sin(t1) * ry), width * p.s, 4));
  }
  // group() maps box fractions, these are already px: map back
  p.group(segs.map((pts) => pts.map(([x, y]) => [x / p.w + 0.5, y / p.s + 1] as Pt)), color);
}

function leaf(p: Pen, x: number, y: number, angle: number, len: number, wid: number, color: string) {
  // len/wid as fractions of box height; angle in radians (0 = up)
  const pts: Pt[] = [];
  const bx = p.X(x), by = p.Y(y);
  const L = len * p.s, Wd = wid * p.s;
  for (let i = 0; i <= 12; i++) {
    const t = i / 12;
    pts.push([Math.sin(Math.PI * t) * Wd * 0.5, -t * L]);
  }
  for (let i = 11; i >= 1; i--) {
    const t = i / 12;
    pts.push([-Math.sin(Math.PI * t) * Wd * 0.5, -t * L]);
  }
  const c = Math.cos(angle), s = Math.sin(angle);
  const rot = pts.map(([px, py]) => [bx + px * c - py * s, by + px * s + py * c] as Pt);
  p.group([rot.map(([px, py]) => [px / p.w + 0.5, py / p.s + 1] as Pt)], color);
}

function heartPts(): Pt[] {
  const pts: Pt[] = [];
  for (let i = 0; i < 40; i++) {
    const t = (i / 40) * Math.PI * 2;
    const x = 16 * Math.sin(t) ** 3;
    const y = 13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t);
    pts.push([0.5 + x / 34, 0.45 - y / 34]);
  }
  return pts;
}

function starPts(cx: number, cy: number, R: number, r: number, aspect: number): Pt[] {
  const pts: Pt[] = [];
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const d = i % 2 ? r : R;
    pts.push([cx + (Math.cos(a) * d) / aspect, cy + Math.sin(a) * d]);
  }
  return pts;
}

export const PROPS: Record<PropName, PropDef> = {
  book: {
    aspect: 0.78,
    held: 0.14,
    draw: (p, o) => {
      const c = o.color ?? "#c8553d";
      p.rrect(0.14, 0.05, 0.82, 0.93, 0.03, "#fbf6ea");
      p.rrect(0.04, 0.02, 0.82, 0.95, 0.04, c);
      p.rect(0.04, 0.02, 0.12, 0.95, dk(c), { shadow: false });
      p.rrect(0.26, 0.22, 0.5, 0.2, 0.02, PAPER, { shadow: false });
      if (o.text) p.text(o.text, 0.51, 0.32, 0.1, INK, HAND_FONT, 0.46);
    },
  },
  scroll: {
    aspect: 0.72,
    held: 0.16,
    draw: (p, o) => {
      p.rect(0.12, 0.1, 0.76, 0.8, o.color ?? "#f3e3bd");
      if (o.text) p.text(o.text, 0.5, 0.3, 0.1, INK, HAND_FONT, 0.66);
      for (let i = 0; i < 5; i++) p.ink([[0.22, 0.44 + i * 0.08], [0.78 - (i % 2) * 0.12, 0.44 + i * 0.08]], "rgba(43,34,48,0.35)", 0.012);
      p.rrect(0.04, 0.03, 0.92, 0.11, 0.05, "#d9b98a");
      p.rrect(0.04, 0.86, 0.92, 0.11, 0.05, "#d9b98a");
    },
  },
  letter: {
    aspect: 1.45,
    held: 0.1,
    draw: (p, o) => {
      p.rect(0.03, 0.08, 0.94, 0.86, o.color ?? "#f3e3bd");
      p.ink([[0.05, 0.12], [0.5, 0.56], [0.95, 0.12]], "rgba(43,34,48,0.45)", 0.025);
      p.circle(0.5, 0.56, 0.11, o.color2 ?? "#b23a3a");
    },
  },
  coin: {
    aspect: 1,
    held: 0.07,
    draw: (p, o) => {
      const c = o.color ?? GOLD;
      p.circle(0.5, 0.5, 0.47, c);
      p.circle(0.5, 0.5, 0.33, dk(c, 0.08), { shadow: false });
      p.ellipse(0.4, 0.36, 0.08, 0.05, lt(c, 0.15), { shadow: false, edge: 0 });
    },
  },
  moneybag: {
    aspect: 0.85,
    held: 0.2,
    draw: (p, o) => {
      const c = o.color ?? "#c8a26a";
      p.group([ell(0.5, 0.64, 0.46, 0.35), [[0.36, 0.1], [0.64, 0.1], [0.58, 0.34], [0.42, 0.34]]], c);
      p.rect(0.36, 0.28, 0.28, 0.07, dk(c, 0.15), { shadow: false });
      p.text("$", 0.5, 0.66, 0.34, dk(c, 0.22), TITLE_FONT);
    },
  },
  crown: {
    aspect: 1.3,
    held: 0.12,
    draw: (p, o) => {
      const c = o.color ?? GOLD;
      p.poly([[0.05, 0.95], [0.05, 0.3], [0.27, 0.58], [0.5, 0.1], [0.73, 0.58], [0.95, 0.3], [0.95, 0.95]], c);
      p.rect(0.05, 0.74, 0.9, 0.21, dk(c, 0.08), { shadow: false });
      p.circle(0.5, 0.84, 0.07, "#d1495b");
      p.circle(0.25, 0.84, 0.05, "#4f7fbf");
      p.circle(0.75, 0.84, 0.05, "#4f7fbf");
      for (const [x, y] of [[0.05, 0.3], [0.5, 0.1], [0.95, 0.3]]) p.circle(x, y, 0.05, lt(c, 0.12));
    },
  },
  sword: {
    aspect: 0.26,
    held: 0.4,
    draw: (p, o) => {
      p.poly([[0.36, 0.72], [0.36, 0.08], [0.5, 0.0], [0.64, 0.08], [0.64, 0.72]], o.color ?? SILVER);
      p.rrect(0.0, 0.7, 1.0, 0.06, 0.02, GOLD);
      p.rect(0.38, 0.76, 0.24, 0.17, WOOD);
      p.circle(0.5, 0.96, 0.035, GOLD);
    },
  },
  flag: {
    aspect: 0.85,
    held: 0.5,
    draw: (p, o) => {
      p.stick(0.1, 1.0, 0.1, 0.0, 0.025, WOOD);
      const top: Pt[] = [], bot: Pt[] = [];
      for (let i = 0; i <= 10; i++) {
        const x = 0.12 + (i / 10) * 0.84;
        const wv = Math.sin(o.t * 5 - i * 0.7) * 0.03 * (i / 10);
        top.push([x, 0.04 + wv]);
        bot.push([x, 0.52 + wv]);
      }
      p.poly([...top, ...bot.reverse()], o.color ?? "#d1495b");
      if (o.color2) {
        const mt = top.map(([x, y]) => [x, y + 0.16] as Pt);
        const mb = top.map(([x, y]) => [x, y + 0.32] as Pt).reverse();
        p.poly([...mt, ...mb], o.color2, { shadow: false });
      }
    },
  },
  candle: {
    aspect: 0.45,
    held: 0.18,
    draw: (p, o) => {
      const f = 1 + 0.12 * Math.sin(o.t * 14) + 0.06 * Math.sin(o.t * 23);
      p.ellipse(0.5, 0.94, 0.48, 0.05, "#b8864b");
      p.rrect(0.28, 0.36, 0.44, 0.58, 0.02, o.color ?? PAPER);
      p.ellipse(0.5, 0.22, 0.2 * f, 0.15 * f, "#f5a623", { shadow: false, edge: 0 });
      p.ellipse(0.5, 0.25, 0.1 * f, 0.08 * f, "#fbe38a", { shadow: false, edge: 0 });
    },
  },
  bottle: {
    aspect: 0.55,
    held: 0.18,
    draw: (p, o) => {
      p.rrect(0.1, 0.34, 0.8, 0.64, 0.1, o.color ?? GLASS);
      p.rect(0.33, 0.13, 0.34, 0.25, o.color ?? GLASS);
      if (o.color2) p.rrect(0.14, 0.64, 0.72, 0.31, 0.08, o.color2, { shadow: false });
      p.rrect(0.29, 0.02, 0.42, 0.14, 0.03, "#c49a6c");
      p.rrect(0.2, 0.46, 0.6, 0.26, 0.02, PAPER, { shadow: false });
      if (o.text) p.text(o.text, 0.5, 0.59, 0.09, INK, HAND_FONT, 0.55);
    },
  },
  pills: {
    aspect: 1.8,
    held: 0.06,
    draw: (p) => {
      for (const [x, y] of [[0.26, 0.62], [0.64, 0.64], [0.45, 0.33]] as Pt[]) {
        p.circle(x, y, 0.3, "#fbfbf6");
        p.ink([[x - 0.1, y - 0.12], [x + 0.1, y + 0.12]], "rgba(43,34,48,0.25)", 0.04);
      }
    },
  },
  cup: {
    aspect: 1,
    held: 0.1,
    draw: (p, o) => {
      const c = o.color ?? "#e07a5f";
      arc(p, 0.76, 0.6, 0.14, 0.17, -Math.PI / 2, Math.PI / 2, 0.08, c);
      p.rrect(0.12, 0.3, 0.62, 0.68, 0.1, c);
      p.ellipse(0.43, 0.32, 0.27, 0.05, dk(c, 0.2), { shadow: false, edge: 0 });
      for (const k of [0, 1]) {
        const pts: Pt[] = [];
        for (let i = 0; i <= 8; i++) pts.push([0.33 + k * 0.18 + Math.sin(i * 0.9 + o.t * 3 + k) * 0.04, 0.24 - i * 0.025]);
        p.ink(pts, "rgba(255,255,255,0.55)", 0.03);
      }
    },
  },
  flask: {
    aspect: 0.8,
    held: 0.16,
    draw: (p, o) => {
      p.poly([[0.38, 0.03], [0.62, 0.03], [0.62, 0.3], [0.95, 0.92], [0.9, 0.98], [0.1, 0.98], [0.05, 0.92], [0.38, 0.3]], GLASS);
      const liq = o.color2 ?? "#7cc47f";
      p.poly([[0.23, 0.58], [0.77, 0.58], [0.92, 0.9], [0.88, 0.95], [0.12, 0.95], [0.08, 0.9]], liq, { shadow: false });
      const r = rng(7);
      for (let i = 0; i < 5; i++) {
        const x = 0.3 + r() * 0.4;
        const y = 0.92 - ((o.t * 0.25 + r()) % 1) * 0.34;
        p.circle(x, y, 0.025 + r() * 0.02, lt(liq, 0.2), { shadow: false, edge: 0 });
      }
      p.rect(0.34, 0.0, 0.32, 0.05, lt(GLASS, 0.05));
    },
  },
  "petri-dish": {
    aspect: 1.5,
    held: 0.07,
    draw: (p, o) => {
      p.ellipse(0.5, 0.52, 0.48, 0.46, "#e6eef0");
      p.ellipse(0.5, 0.52, 0.42, 0.39, "#f1e0b8", { shadow: false });
      const mx = 0.66, my = 0.44;
      if (o.mould) p.ellipse(mx, my, 0.14, 0.2, "#faf1d8", { shadow: false, edge: 0 });
      // bacteria: many small colonies
      const r = rng(11);
      for (let i = 0; i < 70; i++) {
        const a = r() * Math.PI * 2, d = Math.sqrt(r()) * 0.37;
        const x = 0.5 + Math.cos(a) * d, y = 0.52 + Math.sin(a) * d * 0.92;
        const rx = 0.008 + r() * 0.01, ry = rx * 1.5;
        if (o.mould && Math.hypot((x - mx) / 0.16, (y - my) / 0.24) < 1) continue;
        p.ellipse(x, y, rx, ry, "#d9a23a", { shadow: false, edge: 0, texture: 0 });
      }
      if (o.mould) {
        p.group([ell(mx, my, 0.07, 0.1), ell(mx - 0.04, my + 0.03, 0.05, 0.08), ell(mx + 0.04, my - 0.03, 0.05, 0.07)], "#3f8f7f", { edge: 0 });
        p.ellipse(mx, my, 0.03, 0.05, "#2d6e62", { shadow: false, edge: 0 });
      }
    },
  },
  "dish-stack": {
    aspect: 1,
    held: 0.14,
    draw: (p) => {
      const offs = [0.12, 0.2, 0.08, 0.22, 0.14];
      offs.forEach((dx, i) => {
        const y = 0.84 - i * 0.17;
        p.rrect(dx, y, 0.66, 0.14, 0.06, "#e6eef0");
        p.rrect(dx + 0.04, y + 0.04, 0.58, 0.06, 0.03, "#efd9a0", { shadow: false, edge: 0 });
      });
    },
  },
  microscope: {
    aspect: 0.7,
    held: 0.2,
    draw: (p, o) => {
      const c = o.color ?? "#3d4b5c";
      p.rrect(0.08, 0.88, 0.84, 0.12, 0.04, c);
      p.group(
        [capsulePts(p.X(0.66), p.Y(0.9), p.X(0.74), p.Y(0.55), 0.13 * p.s), capsulePts(p.X(0.74), p.Y(0.55), p.X(0.58), p.Y(0.28), 0.13 * p.s)].map((pts) =>
          pts.map(([x, y]) => [x / p.w + 0.5, y / p.s + 1] as Pt),
        ),
        c,
      );
      p.rect(0.14, 0.6, 0.56, 0.06, c);
      p.stick(0.5, 0.42, 0.34, 0.06, 0.13, SILVER);
      p.rect(0.26, 0.0, 0.18, 0.08, dk(SILVER, 0.15));
      p.stick(0.46, 0.44, 0.44, 0.54, 0.07, dk(SILVER, 0.2));
      p.circle(0.76, 0.6, 0.06, SILVER);
    },
  },
  apple: {
    aspect: 1,
    held: 0.08,
    draw: (p, o) => {
      p.group([ell(0.36, 0.6, 0.34, 0.36), ell(0.64, 0.6, 0.34, 0.36)], o.color ?? "#d64545");
      p.stick(0.5, 0.3, 0.55, 0.08, 0.05, "#6b4a2b");
      leaf(p, 0.56, 0.18, 1.1, 0.24, 0.12, "#5f9a4f");
    },
  },
  basket: {
    aspect: 1.25,
    held: 0.16,
    draw: (p, o) => {
      const c = o.color ?? "#c8955a";
      arc(p, 0.5, 0.48, 0.38, 0.44, Math.PI, 2 * Math.PI, 0.06, dk(c, 0.1));
      if (o.color2) for (const x of [0.3, 0.5, 0.7]) p.circle(x, 0.42, 0.12, o.color2);
      p.poly([[0.05, 0.45], [0.95, 0.45], [0.85, 0.98], [0.15, 0.98]], c);
      for (let i = 1; i < 4; i++) p.ink([[0.1 + i * 0.01, 0.45 + i * 0.13], [0.9 - i * 0.01, 0.45 + i * 0.13]], dk(c, 0.2), 0.015);
      for (let i = 1; i < 7; i++) p.ink([[0.05 + i * 0.13, 0.47], [0.15 + i * 0.1, 0.96]], dk(c, 0.2), 0.012);
      p.rrect(0.02, 0.4, 0.96, 0.09, 0.04, dk(c, 0.06));
    },
  },
  bucket: {
    aspect: 0.9,
    held: 0.16,
    draw: (p, o) => {
      const c = o.color ?? "#8a9bb0";
      arc(p, 0.5, 0.3, 0.4, 0.3, Math.PI, 2 * Math.PI, 0.03, INK);
      p.poly([[0.1, 0.25], [0.9, 0.25], [0.8, 0.98], [0.2, 0.98]], c);
      p.ellipse(0.5, 0.27, 0.38, 0.05, o.color2 ?? "#4f9bd1", { shadow: false, edge: 0 });
      p.rect(0.12, 0.45, 0.76, 0.05, dk(c), { shadow: false });
      p.rect(0.17, 0.8, 0.66, 0.05, dk(c), { shadow: false });
    },
  },
  chest: {
    aspect: 1.35,
    held: 0.2,
    draw: (p, o) => {
      const c = o.color ?? WOOD;
      p.rrect(0.05, 0.45, 0.9, 0.53, 0.03, c);
      p.rrect(0.05, 0.1, 0.9, 0.38, 0.16, lt(c, 0.06));
      for (const x of [0.18, 0.74]) p.rect(x, 0.1, 0.08, 0.88, GOLD, { shadow: false });
      p.rrect(0.42, 0.38, 0.16, 0.2, 0.03, GOLD);
      p.circle(0.5, 0.47, 0.03, INK, { shadow: false, edge: 0 });
    },
  },
  key: {
    aspect: 2.4,
    held: 0.08,
    draw: (p, o) => {
      const c = o.color ?? GOLD;
      p.circle(0.17, 0.5, 0.36, c);
      p.circle(0.17, 0.5, 0.16, dk(c, 0.15), { shadow: false });
      p.rect(0.28, 0.42, 0.66, 0.16, c);
      p.rect(0.72, 0.56, 0.07, 0.3, c, { shadow: false });
      p.rect(0.86, 0.56, 0.07, 0.22, c, { shadow: false });
    },
  },
  clock: {
    aspect: 1,
    held: 0.14,
    draw: (p, o) => {
      p.circle(0.5, 0.5, 0.48, o.color ?? WOOD);
      p.circle(0.5, 0.5, 0.4, PAPER, { shadow: false });
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2;
        p.ink([[0.5 + Math.cos(a) * 0.33, 0.5 + Math.sin(a) * 0.33], [0.5 + Math.cos(a) * 0.37, 0.5 + Math.sin(a) * 0.37]], INK, 0.02);
      }
      const hA = -Math.PI / 2 + o.t * 0.25, mA = -Math.PI / 2 + o.t * 2.2;
      p.ink([[0.5, 0.5], [0.5 + Math.cos(hA) * 0.2, 0.5 + Math.sin(hA) * 0.2]], INK, 0.045);
      p.ink([[0.5, 0.5], [0.5 + Math.cos(mA) * 0.3, 0.5 + Math.sin(mA) * 0.3]], INK, 0.03);
      p.circle(0.5, 0.5, 0.03, "#d1495b", { shadow: false, edge: 0 });
    },
  },
  hourglass: {
    aspect: 0.6,
    held: 0.18,
    draw: (p, o) => {
      p.poly([[0.16, 0.08], [0.84, 0.08], [0.55, 0.5], [0.84, 0.92], [0.16, 0.92], [0.45, 0.5]], GLASS);
      const sand = o.color2 ?? "#e9c46a";
      const k = (o.t / 8) % 1; // one turn every 8 seconds
      const top = 0.12 + k * 0.34;
      const wTop = 0.34 * (1 - (top - 0.08) / 0.42);
      p.poly([[0.5 - wTop, top], [0.5 + wTop, top], [0.52, 0.48], [0.48, 0.48]], sand, { shadow: false, edge: 0 });
      const h = 0.06 + k * 0.28;
      p.poly([[0.2, 0.9], [0.8, 0.9], [0.5 + 0.08, 0.9 - h], [0.5 - 0.08, 0.9 - h]], sand, { shadow: false, edge: 0 });
      p.ink([[0.5, 0.5], [0.5, 0.9 - h]], sand, 0.012);
      for (const x of [0.08, 0.92]) p.stick(x, 0.06, x, 0.94, 0.05, WOOD);
      p.rrect(0.0, 0.0, 1.0, 0.08, 0.02, o.color ?? WOOD);
      p.rrect(0.0, 0.92, 1.0, 0.08, 0.02, o.color ?? WOOD);
    },
  },
  globe: {
    aspect: 0.8,
    held: 0.2,
    draw: (p, o) => {
      p.ellipse(0.5, 0.95, 0.36, 0.05, WOOD);
      p.rect(0.46, 0.78, 0.08, 0.16, WOOD);
      arc(p, 0.5, 0.42, 0.46, 0.4, Math.PI * 0.35, Math.PI * 1.1, 0.035, GOLD_DK);
      p.circle(0.5, 0.42, 0.36, o.color ?? "#4f9bd1");
      const ctx = p.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.arc(p.X(0.5), p.Y(0.42), 0.35 * p.s, 0, Math.PI * 2);
      ctx.clip();
      const spin = (o.t * 0.08) % 1;
      for (const [x, y, rx, ry] of [[0.3, 0.3, 0.14, 0.12], [0.62, 0.5, 0.18, 0.14], [0.45, 0.62, 0.1, 0.07], [0.9, 0.3, 0.12, 0.1]]) {
        for (const wrap of [0, -1.2]) p.ellipse(((x + spin * 1.2 + wrap + 1.2) % 1.2) - 0.1, y, rx, ry, o.color2 ?? "#7fb069", { shadow: false, edge: 0 });
      }
      ctx.restore();
    },
  },
  lightbulb: {
    aspect: 0.65,
    held: 0.14,
    draw: (p, o) => {
      const c = o.color ?? "#f7d65a";
      const ctx = p.ctx;
      const glow = 0.8 + 0.2 * Math.sin(o.t * 4);
      const g = ctx.createRadialGradient(p.X(0.5), p.Y(0.38), 0, p.X(0.5), p.Y(0.38), 0.62 * p.s * glow);
      g.addColorStop(0, "rgba(255,230,120,0.55)");
      g.addColorStop(1, "rgba(255,230,120,0)");
      ctx.fillStyle = g;
      ctx.fillRect(p.X(-0.5), p.Y(-0.3), p.w * 2, p.s * 1.6);
      p.group([ell(0.5, 0.36, 0.48, 0.34), [[0.32, 0.6], [0.68, 0.6], [0.62, 0.74], [0.38, 0.74]]], c);
      p.ink([[0.42, 0.62], [0.44, 0.42], [0.5, 0.5], [0.56, 0.42], [0.58, 0.62]], "rgba(140,90,20,0.7)", 0.018);
      p.rrect(0.34, 0.72, 0.32, 0.2, 0.03, "#9aa3a8");
      for (let i = 0; i < 3; i++) p.ink([[0.35, 0.77 + i * 0.05], [0.65, 0.76 + i * 0.05]], "#6b7479", 0.015);
    },
  },
  heart: { aspect: 1.1, held: 0.1, draw: (p, o) => p.poly(heartPts(), o.color ?? "#d1495b") },
  star: { aspect: 1, held: 0.1, draw: (p, o) => p.poly(starPts(0.5, 0.53, 0.48, 0.2, 1), o.color ?? "#f4c542") },
  trophy: {
    aspect: 0.8,
    held: 0.18,
    draw: (p, o) => {
      const c = o.color ?? GOLD;
      arc(p, 0.18, 0.22, 0.14, 0.14, Math.PI * 0.5, Math.PI * 1.5, 0.06, c);
      arc(p, 0.82, 0.22, 0.14, 0.14, -Math.PI * 0.5, Math.PI * 0.5, 0.06, c);
      p.poly([[0.15, 0.04], [0.85, 0.04], [0.75, 0.42], [0.56, 0.58], [0.44, 0.58], [0.25, 0.42]], c);
      p.rect(0.44, 0.56, 0.12, 0.22, dk(c, 0.08));
      p.rrect(0.22, 0.78, 0.56, 0.2, 0.03, WOOD);
      p.poly(starPts(0.5, 0.26, 0.12, 0.05, 0.8), lt(c, 0.12), { shadow: false, edge: 0 });
    },
  },
  gift: {
    aspect: 1,
    held: 0.14,
    draw: (p, o) => {
      const c = o.color ?? "#e07a5f", r = o.color2 ?? "#f2cc8f";
      p.ellipse(0.36, 0.2, 0.15, 0.09, r);
      p.ellipse(0.64, 0.2, 0.15, 0.09, r);
      p.rrect(0.08, 0.36, 0.84, 0.62, 0.03, c);
      p.rrect(0.03, 0.26, 0.94, 0.14, 0.02, dk(c, 0.05));
      p.rect(0.44, 0.26, 0.12, 0.72, r, { shadow: false });
      p.circle(0.5, 0.24, 0.06, dk(r, 0.08));
    },
  },
  suitcase: {
    aspect: 1.35,
    held: 0.2,
    draw: (p, o) => {
      const c = o.color ?? "#c98b52";
      arc(p, 0.5, 0.26, 0.15, 0.2, Math.PI, 2 * Math.PI, 0.07, dk(c, 0.18));
      p.rrect(0.03, 0.22, 0.94, 0.76, 0.06, c);
      for (const x of [0.24, 0.69]) p.rect(x, 0.22, 0.07, 0.76, dk(c, 0.14), { shadow: false });
      for (const x of [0.22, 0.67]) p.rrect(x, 0.2, 0.11, 0.07, 0.01, GOLD, { shadow: false });
    },
  },
  umbrella: {
    aspect: 1,
    held: 0.4,
    draw: (p, o) => {
      p.stick(0.5, 0.12, 0.5, 0.86, 0.03, INK);
      arc(p, 0.58, 0.86, 0.08, 0.08, 0, Math.PI, 0.03, INK);
      const pts: Pt[] = [];
      for (let i = 0; i <= 20; i++) {
        const a = Math.PI + (i / 20) * Math.PI;
        pts.push([0.5 + Math.cos(a) * 0.48, 0.5 + Math.sin(a) * 0.44]);
      }
      for (let i = 4; i >= 0; i--) {
        for (let k = 0; k <= 4; k++) {
          const x = 0.02 + ((i + (4 - k) / 4) / 5) * 0.96;
          pts.push([x, 0.5 - Math.sin(((4 - k) / 4) * Math.PI) * 0.06]);
        }
      }
      p.poly(pts, o.color ?? "#d1495b");
    },
  },
  house: {
    aspect: 0.9,
    held: 0.3,
    draw: (p, o) => {
      p.rect(0.66, 0.1, 0.1, 0.24, o.color2 ?? "#8e4b3e");
      p.rect(0.12, 0.42, 0.76, 0.56, o.color ?? "#e9a15b");
      p.poly([[0.02, 0.46], [0.5, 0.04], [0.98, 0.46]], o.color2 ?? "#8e4b3e");
      p.rrect(0.42, 0.66, 0.18, 0.32, 0.02, WOOD);
      p.rect(0.2, 0.56, 0.16, 0.15, "#fbf3d6");
      p.ink([[0.28, 0.56], [0.28, 0.71]], WOOD, 0.015);
      p.ink([[0.2, 0.635], [0.36, 0.635]], WOOD, 0.015);
    },
  },
  boat: {
    aspect: 1.15,
    held: 0.3,
    draw: (p, o) => {
      p.stick(0.5, 0.64, 0.5, 0.03, 0.03, WOOD);
      p.poly([[0.54, 0.06], [0.54, 0.58], [0.92, 0.58]], PAPER);
      p.poly([[0.46, 0.12], [0.46, 0.58], [0.16, 0.58]], o.color2 ?? "#e07a5f");
      p.poly([[0.02, 0.6], [0.98, 0.6], [0.82, 0.98], [0.18, 0.98]], o.color ?? WOOD);
      p.rect(0.08, 0.7, 0.84, 0.06, lt(o.color ?? WOOD, 0.12), { shadow: false });
    },
  },
  rock: {
    aspect: 1.5,
    held: 0.1,
    draw: (p, o) => {
      const c = o.color ?? "#9aa3a8";
      p.group([ell(0.5, 0.62, 0.46, 0.38), ell(0.36, 0.48, 0.26, 0.3), ell(0.66, 0.5, 0.24, 0.28)], c);
      p.ellipse(0.62, 0.72, 0.18, 0.12, dk(c, 0.08), { shadow: false, edge: 0 });
    },
  },
  well: {
    aspect: 0.9,
    held: 0.4,
    draw: (p, o) => {
      const c = o.color ?? "#9aa3a8";
      for (const x of [0.18, 0.82]) p.stick(x, 0.6, x, 0.16, 0.05, WOOD);
      p.stick(0.18, 0.26, 0.82, 0.26, 0.035, WOOD);
      p.ink([[0.5, 0.26], [0.5, 0.44]], INK, 0.012);
      p.rrect(0.43, 0.44, 0.14, 0.1, 0.02, "#8a9bb0");
      p.poly([[0.04, 0.2], [0.5, 0.0], [0.96, 0.2]], o.color2 ?? "#8e4b3e");
      p.rrect(0.1, 0.55, 0.8, 0.43, 0.04, c);
      for (let r = 0; r < 3; r++) for (let k = 0; k < 4; k++) p.ink([[0.12 + k * 0.2 + (r % 2) * 0.1, 0.62 + r * 0.12], [0.26 + k * 0.2 + (r % 2) * 0.1, 0.62 + r * 0.12]], dk(c, 0.18), 0.012);
    },
  },
  sign: {
    aspect: 1.15,
    held: 0.35,
    draw: (p, o) => {
      p.rect(0.45, 0.5, 0.1, 0.5, WOOD);
      p.rrect(0.02, 0.04, 0.96, 0.5, 0.04, o.color ?? "#c8955a");
      if (o.text) p.text(o.text, 0.5, 0.3, 0.2, INK, HAND_FONT, 0.86);
    },
  },
  chair: {
    aspect: 0.68,
    held: 0.4,
    draw: (p, o) => {
      const c = o.color ?? WOOD;
      p.rect(0.1, 0.58, 0.1, 0.42, dk(c));
      p.rect(0.8, 0.58, 0.1, 0.42, dk(c));
      p.rrect(0.1, 0.0, 0.8, 0.5, 0.06, c);
      p.rrect(0.22, 0.1, 0.56, 0.28, 0.04, lt(c, 0.08), { shadow: false });
      p.rrect(0.02, 0.5, 0.96, 0.11, 0.02, c);
    },
  },
  plant: {
    aspect: 0.72,
    held: 0.2,
    draw: (p, o) => {
      const sway = Math.sin(o.t * 1.6) * 0.08;
      const g = o.color2 ?? "#5f9a4f";
      leaf(p, 0.5, 0.64, -0.7 + sway, 0.42, 0.18, dk(g, 0.05));
      leaf(p, 0.5, 0.64, 0.7 + sway, 0.4, 0.18, dk(g, 0.05));
      leaf(p, 0.5, 0.64, sway, 0.56, 0.2, g);
      leaf(p, 0.5, 0.64, -0.3 + sway, 0.48, 0.16, lt(g, 0.06));
      p.poly([[0.18, 0.64], [0.82, 0.64], [0.72, 0.98], [0.28, 0.98]], o.color ?? "#c8663d");
      p.rect(0.14, 0.6, 0.72, 0.08, dk(o.color ?? "#c8663d", 0.05));
    },
  },
  phone: {
    aspect: 0.5,
    held: 0.1,
    draw: (p, o) => {
      p.rrect(0.05, 0.0, 0.9, 1.0, 0.08, o.color ?? "#2f3542");
      p.rrect(0.13, 0.07, 0.74, 0.8, 0.03, o.color2 ?? "#9dd0ea", { shadow: false });
      p.circle(0.5, 0.94, 0.03, "#6b7479", { shadow: false, edge: 0 });
    },
  },
  laptop: {
    aspect: 1.45,
    held: 0.2,
    draw: (p, o) => {
      p.rrect(0.12, 0.0, 0.76, 0.72, 0.03, o.color ?? "#4b5563");
      p.rrect(0.16, 0.05, 0.68, 0.6, 0.02, o.color2 ?? "#9dd0ea", { shadow: false });
      p.poly([[0.06, 0.72], [0.94, 0.72], [1.0, 0.94], [0.0, 0.94]], "#9aa3a8");
      p.rect(0.4, 0.86, 0.2, 0.04, "#7d868c", { shadow: false, edge: 0 });
    },
  },
  arrow: {
    aspect: 1.9,
    held: 0.2,
    draw: (p, o) => p.poly([[0.02, 0.35], [0.6, 0.35], [0.6, 0.08], [0.98, 0.5], [0.6, 0.92], [0.6, 0.65], [0.02, 0.65]], o.color ?? "#d1495b"),
  },
  shapes: {
    aspect: 1,
    held: 0.15,
    draw: (p, o) => {
      for (const s of o.shapes ?? []) {
        if (s.type === "rect") p.rrect(s.x, s.y, s.w, s.h, s.round ?? 0, s.color);
        else if (s.type === "circle") p.circle(s.x, s.y, s.r, s.color);
        else if (s.type === "ellipse") p.ellipse(s.x, s.y, s.rx, s.ry, s.color);
        else if (s.type === "poly") p.poly(s.points, s.color);
      }
    },
  },
};

// Draw a prop with its bottom-centre at the current origin.
export function drawProp(ctx: CanvasRenderingContext2D, name: PropName, heightPx: number, seed: number, o: PropOpts, aspect?: number) {
  const def = PROPS[name] ?? PROPS.shapes;
  const pen = new Pen(ctx, heightPx, aspect ?? def.aspect, seed);
  def.draw(pen, o);
}

export const propAspect = (name: PropName, aspect?: number) => aspect ?? (PROPS[name] ?? PROPS.shapes).aspect;
