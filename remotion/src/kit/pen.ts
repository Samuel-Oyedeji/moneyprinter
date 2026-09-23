import { ellipsePts, paper, paperGroup, PaperOpts, Pt, rectPts } from "./paper";

// Draws paper shapes inside one object's box. Coordinates are fractions of
// the box: x 0 = left, 1 = right (of its width); y 0 = top, 1 = bottom (of
// its height). The box's bottom-centre sits at the canvas origin, so the
// caller only has to translate/rotate to where the object stands.
//
// Torn edges, shadows and brush strokes shrink with the object so a small
// cup looks cut from the same paper as a big hill.

export function roundRectPts(x: number, y: number, w: number, h: number, r: number): Pt[] {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  if (r === 0) return rectPts(x, y, w, h);
  const pts: Pt[] = [];
  const corner = (cx: number, cy: number, a0: number) => {
    for (let i = 0; i <= 5; i++) {
      const a = a0 + (i / 5) * (Math.PI / 2);
      pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
    }
  };
  corner(x + w - r, y + r, -Math.PI / 2);
  corner(x + w - r, y + h - r, 0);
  corner(x + r, y + h - r, Math.PI / 2);
  corner(x + r, y + r, Math.PI);
  return pts;
}

// A limb or stick: a rectangle with round ends from (x0,y0) to (x1,y1).
export function capsulePts(x0: number, y0: number, x1: number, y1: number, w: number, n = 7): Pt[] {
  const a = Math.atan2(y1 - y0, x1 - x0);
  const r = w / 2;
  const pts: Pt[] = [];
  for (let i = 0; i <= n; i++) {
    const t = a - Math.PI / 2 + (i / n) * Math.PI;
    pts.push([x1 + Math.cos(t) * r, y1 + Math.sin(t) * r]);
  }
  for (let i = 0; i <= n; i++) {
    const t = a + Math.PI / 2 + (i / n) * Math.PI;
    pts.push([x0 + Math.cos(t) * r, y0 + Math.sin(t) * r]);
  }
  return pts;
}

export class Pen {
  private k = 0;
  readonly w: number;
  constructor(
    readonly ctx: CanvasRenderingContext2D,
    readonly s: number, // box height in px
    aspect: number, // box width / height
    readonly seed: number,
  ) {
    this.w = s * aspect;
  }

  X = (fx: number) => (fx - 0.5) * this.w;
  Y = (fy: number) => (fy - 1) * this.s;

  // paper options scaled to this object's size
  opts(o: PaperOpts = {}): PaperOpts {
    const s = this.s;
    return {
      edge: Math.min(6, Math.max(2, s * 0.022)),
      rough: Math.min(4, Math.max(1.2, s * 0.012)),
      texture: 0.8,
      brush: Math.min(1, Math.max(0.22, s / 500)),
      lift: Math.min(1, Math.max(0.35, s / 320)),
      ...o,
    };
  }

  private next() {
    this.k += 1;
    return this.seed + this.k * 101;
  }

  poly(points: Pt[], color: string, o?: PaperOpts) {
    paper(this.ctx, points.map(([x, y]) => [this.X(x), this.Y(y)] as Pt), color, this.next(), this.opts(o));
  }
  rect(x: number, y: number, w: number, h: number, color: string, o?: PaperOpts) {
    paper(this.ctx, rectPts(this.X(x), this.Y(y), w * this.w, h * this.s), color, this.next(), this.opts(o));
  }
  rrect(x: number, y: number, w: number, h: number, r: number, color: string, o?: PaperOpts) {
    paper(this.ctx, roundRectPts(this.X(x), this.Y(y), w * this.w, h * this.s, r * this.s), color, this.next(), this.opts(o));
  }
  ellipse(x: number, y: number, rx: number, ry: number, color: string, o?: PaperOpts) {
    paper(this.ctx, ellipsePts(this.X(x), this.Y(y), rx * this.w, ry * this.s, 36), color, this.next(), this.opts(o));
  }
  // r is a fraction of the box height
  circle(x: number, y: number, r: number, color: string, o?: PaperOpts) {
    paper(this.ctx, ellipsePts(this.X(x), this.Y(y), r * this.s, r * this.s, 32), color, this.next(), this.opts(o));
  }
  stick(x0: number, y0: number, x1: number, y1: number, width: number, color: string, o?: PaperOpts) {
    paper(this.ctx, capsulePts(this.X(x0), this.Y(y0), this.X(x1), this.Y(y1), width * this.s), color, this.next(), this.opts(o));
  }
  // several shapes cut from one sheet, no seams between them
  group(shapes: Pt[][], color: string, o?: PaperOpts) {
    paperGroup(this.ctx, shapes.map((pts) => pts.map(([x, y]) => [this.X(x), this.Y(y)] as Pt)), color, this.next(), this.opts(o));
  }
  // flat ink line (no paper edge), width as a fraction of box height
  ink(points: Pt[], color: string, width: number, close = false) {
    const ctx = this.ctx;
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1.5, width * this.s);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    points.forEach(([x, y], i) => (i ? ctx.lineTo(this.X(x), this.Y(y)) : ctx.moveTo(this.X(x), this.Y(y))));
    if (close) ctx.closePath();
    ctx.stroke();
  }
  text(str: string, x: number, y: number, size: number, color: string, font: string, maxW = 0.9) {
    const ctx = this.ctx;
    let px = size * this.s;
    ctx.font = `${px}px ${font}`;
    while (px > 8 && ctx.measureText(str).width > maxW * this.w) {
      px -= 2;
      ctx.font = `${px}px ${font}`;
    }
    ctx.fillStyle = color;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(str, this.X(x), this.Y(y));
  }
}

// helpers for building point lists in box fractions
export const ell = (x: number, y: number, rx: number, ry: number, n = 28): Pt[] => ellipsePts(x, y, rx, ry, n);
export const box = (x: number, y: number, w: number, h: number): Pt[] => rectPts(x, y, w, h);
