import { Easing } from "remotion";
import type { Character, Scene, Transition } from "../types";
import { isPerson } from "../types";
import { cameraAt, clamp01, span } from "../kit/camera";
import type { CamState } from "../kit/camera";
import type { DrawFn } from "../kit/PaperCanvas";
import { boil, ellipsePts, paper, paperGroup, rectPts, shade } from "../kit/paper";
import type { PaperOpts, Pt } from "../kit/paper";
import { capsulePts, roundRectPts } from "../kit/pen";
import { onTwos } from "../kit/motion";
import { defaultExtras, PALETTES } from "../kit/palettes";
import { propAspect } from "../props/library";
import { lookOf, SKINS } from "../puppet/character";

// Transitions that happen inside the picture: a bird flies into the lens, a
// person's hand covers the camera, the camera flies into a window, a hand
// pulls the page away. Each one straddles the cut; the scene behind is
// revealed while something in the picture covers the join.

export type Spec =
  | { type: "tear" }
  | { type: "cut" }
  | { type: "fly"; from: "left" | "right"; color: string }
  | { type: "hand"; who?: string }
  | { type: "zoom"; x: number; y: number; w: number; h: number; shape: "rect" | "circle"; depth: number; frame?: "window" }
  | { type: "pull"; corner: "top-right" | "top-left" };
export type ZoomSpec = Extract<Spec, { type: "zoom" }>;
export type PullSpec = Extract<Spec, { type: "pull" }>;

export const TRANSITION_SECONDS: Record<Spec["type"], number> = { tear: 0.7, cut: 0, fly: 1.4, hand: 1.3, zoom: 1.5, pull: 1.3 };

// Round things are flown into through a circle, everything else a rectangle.
const ROUND_PROPS = ["clock", "globe", "coin", "petri-dish", "apple"];

// Where a named thing sits in the previous scene, in the same geometry its
// drawing code uses (Backdrop window/sun/moon, scenery planet/earth, props).
function zoomTarget(into: string, prev: Scene | undefined, W: number, H: number): Omit<ZoomSpec, "type"> | null {
  if (!prev) return null;
  const name = into.trim().toLowerCase();
  const extras = [...(prev.backdrop.noDefaults ? [] : defaultExtras(prev.backdrop.sky)), ...(prev.backdrop.extras ?? [])];
  const round = (x: number, y: number, r: number, depth: number) => ({ x, y, w: (2 * r) / W, h: (2 * r) / H, shape: "circle" as const, depth });
  for (const e of extras) {
    if (e.type !== name) continue;
    if (e.type === "window") {
      const s = e.size ?? 1;
      return { x: e.x ?? 0.74, y: e.y ?? 0.3, w: (300 * s) / W, h: (380 * s) / H, shape: "rect", depth: 0.12, frame: "window" };
    }
    if (e.type === "sun") return round(e.x ?? 0.8, e.y ?? 0.12, 78 * (e.size ?? 1), 0.16);
    if (e.type === "moon") return round(e.x ?? 0.2, e.y ?? 0.1, 70 * (e.size ?? 1), 0.14);
    if (e.type === "planet") return round(e.x ?? 0.76, e.y ?? 0.2, 110 * (e.size ?? 1), 0.12);
    if (e.type === "earth") return round(e.x ?? 0.72, e.y ?? 0.24, 130 * (e.size ?? 1), 0.12);
  }
  for (const a of prev.actors ?? []) {
    if (isPerson(a) || (a.name?.toLowerCase() !== name && a.prop !== name)) continue;
    const aspect = propAspect(a.prop, a.aspect);
    return {
      x: a.x,
      y: a.y - a.height / 2,
      w: (a.height * H * aspect) / W,
      h: a.height,
      shape: ROUND_PROPS.includes(a.prop) ? "circle" : "rect",
      depth: a.depth ?? 1,
    };
  }
  return null;
}

// A scene's transition, resolved against the scene before it. Anything that
// can't be done (a zoom into something that isn't there) falls back to the tear.
export function transitionSpec(t: Transition | undefined, prev?: Scene, W = 1080, H = 1920): Spec {
  if (!t || t === "tear") return { type: "tear" };
  if (t === "cut") return { type: "cut" };
  switch (t.type) {
    case "fly":
      return { type: "fly", from: t.from ?? "left", color: t.color ?? "#3d6fb0" };
    case "hand":
      return { type: "hand", who: t.who };
    case "zoom": {
      if (t.x !== undefined && t.y !== undefined && t.w !== undefined && t.h !== undefined) {
        return { type: "zoom", x: t.x, y: t.y, w: t.w, h: t.h, shape: t.shape ?? "rect", depth: t.depth ?? 1, frame: t.frame };
      }
      const target = t.into ? zoomTarget(t.into, prev, W, H) : null;
      return target ? { type: "zoom", ...target } : { type: "tear" };
    }
    case "pull":
      return { type: "pull", corner: t.corner ?? "top-right" };
    case "cut":
      return { type: "cut" };
    default:
      return { type: "tear" };
  }
}

// ------------------------------------------------------------ helpers

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

// Map points in a carrier's own units (1 unit = S px; x forward, y down) to
// the screen, rotated about its centre and mirrored when flip = -1.
function placer(cx: number, cy: number, S: number, rotDeg: number, flip = 1) {
  const a = (rotDeg * Math.PI) / 180;
  const c = Math.cos(a);
  const s = Math.sin(a);
  return (pts: Pt[]): Pt[] =>
    pts.map(([u, v]) => {
      const x = u * S * flip;
      const y = v * S;
      return [cx + x * c - y * s, cy + x * s + y * c];
    });
}

// Paper settings for something S px per unit: the torn edge and brush grow
// with it, within limits, so a hand filling the frame is still paper.
const big = (S: number): PaperOpts => ({
  edge: clamp(S * 0.02, 4, 12),
  rough: clamp(S * 0.012, 2, 6),
  brush: clamp(S / 300, 0.5, 3),
  lift: clamp(S / 300, 0.5, 2.5),
  texture: 1,
});

// Something approaching the lens grows like 1 / distance: slowly, then fast.
const approach = (S0: number, S1: number, q: number) => S0 / (1 - q * (1 - S0 / S1));

// ------------------------------------------------------------ fly: a paper bird

const BIRD_BODY = { rx: 0.55, ry: 0.28 };
const BIRD_TAIL: Pt[] = [[-0.42, -0.06], [-0.98, -0.26], [-0.84, 0.0], [-0.98, 0.22], [-0.42, 0.08]];
const BIRD_WING: Pt[] = [
  [-0.3, 0.02], [0.2, 0.02], [0.14, -0.3], [0.02, -0.62], [-0.16, -0.92], // leading edge to the tip
  [-0.22, -0.76], [-0.3, -0.8], [-0.32, -0.6], [-0.4, -0.62], [-0.4, -0.42], [-0.48, -0.42], [-0.44, -0.2], // feathered trailing edge
];
const BIRD_BEAK: Pt[] = [[0.64, -0.2], [0.92, -0.1], [0.64, -0.02]];

function drawBird(ctx: CanvasRenderingContext2D, cx: number, cy: number, S: number, rot: number, flip: number, flap: number, color: string, seed: number) {
  const at = placer(cx, cy, S, rot * flip, flip);
  const o = big(S);
  // a wing hinged on the back; lift 1 = straight up, -1 = straight down
  const wing = (lift: number, dx: number) => BIRD_WING.map(([u, v]) => [u + 0.02 + dx, -0.1 + v * lift] as Pt);
  paper(ctx, at(wing(Math.cos(flap + 0.35), 0.08)), shade(color, -0.14), seed + 1, o);
  paper(ctx, at(BIRD_TAIL), shade(color, -0.06), seed + 2, o);
  paperGroup(ctx, [at(ellipsePts(0, 0, BIRD_BODY.rx, BIRD_BODY.ry, 40)), at(ellipsePts(0.5, -0.14, 0.2, 0.2, 28))], color, seed + 3, o);
  paper(ctx, at(ellipsePts(0.06, 0.1, 0.4, 0.14, 32)), "#f2e6c9", seed + 4, { ...o, shadow: false });
  paper(ctx, at(BIRD_BEAK), "#e8913a", seed + 5, o);
  paper(ctx, at(ellipsePts(0.58, -0.18, 0.055, 0.055, 16)), "#fbf7ee", seed + 6, { ...o, shadow: false, edge: 0 });
  const [[px, py]] = at([[0.595, -0.18]]);
  ctx.fillStyle = "#1c1f3a";
  ctx.beginPath();
  ctx.arc(px, py, 0.03 * S, 0, Math.PI * 2);
  ctx.fill();
  paper(ctx, at(wing(Math.cos(flap), 0)), shade(color, 0.1), seed + 7, o);
}

// The bird crosses the sky toward the camera, fills the frame with its body
// at the cut, and swoops out past the lens.
export function flyDraw(spec: Extract<Spec, { type: "fly" }>, frames: number): DrawFn {
  return (ctx, frame, fps, W, H) => {
    const p = clamp01(frame / frames);
    const flip = spec.from === "right" ? -1 : 1;
    const cover = 1.1 * Math.hypot(W / 2 / BIRD_BODY.rx, H / 2 / BIRD_BODY.ry);
    const flap = onTwos(frame / fps) * Math.PI * 2 * 3.2;
    let cx: number, cy: number, S: number, rot: number;
    if (p <= 0.5) {
      const q = p / 0.5;
      S = approach(0.15 * Math.min(W, H), cover, q);
      const [x0, y0] = [flip > 0 ? -0.1 * W : 1.1 * W, 0.3 * H];
      const [x1, y1] = [flip > 0 ? 0.28 * W : 0.72 * W, 0.12 * H];
      cx = (1 - q) * (1 - q) * x0 + 2 * (1 - q) * q * x1 + q * q * (W / 2);
      cy = (1 - q) * (1 - q) * y0 + 2 * (1 - q) * q * y1 + q * q * (H / 2);
      rot = -12 * (1 - q);
    } else {
      const e = Easing.out(Easing.quad)((p - 0.5) / 0.5);
      S = cover;
      const L = W / 2 + 1.25 * S;
      cx = W / 2 + flip * L * e;
      cy = H / 2 + 0.25 * L * e;
      rot = 8 * e;
    }
    drawBird(ctx, cx, cy, S, rot, flip, flap, spec.color, 8800 + boil(frame, 3) * 13);
  };
}

// ------------------------------------------------------------ hand: a palm to the lens

function drawPalm(ctx: CanvasRenderingContext2D, cx: number, cy: number, S: number, rot: number, skin: string, sleeve: string, seed: number, near: number) {
  const at = placer(cx, cy, S, rot);
  // a hand right against the lens blocks the light: darken it as it nears
  skin = shade(skin, -0.22 * near);
  sleeve = shade(sleeve, -0.22 * near);
  const o = big(S);
  paper(ctx, at(rectPts(-0.56, 0.55, 1.12, 3.2)), sleeve, seed + 1, o);
  paper(ctx, at(rectPts(-0.6, 0.55, 1.2, 0.2)), shade(sleeve, -0.1), seed + 2, o);
  const fingers: [number, number, number][] = [[-0.36, 0.6, -0.06], [-0.12, 0.72, -0.02], [0.12, 0.67, 0.02], [0.35, 0.5, 0.07]];
  paperGroup(
    ctx,
    [
      at(roundRectPts(-0.5, -0.55, 1.0, 1.1, 0.2)),
      at(rectPts(-0.36, 0.3, 0.72, 0.4)),
      ...fingers.map(([x, len, lean]) => at(capsulePts(x, -0.4, x + lean * len * 2, -0.45 - len, 0.22))),
      at(capsulePts(0.36, 0.22, 0.8, -0.18, 0.26)),
    ],
    skin,
    seed + 3,
    o,
  );
  // palm creases
  ctx.strokeStyle = shade(skin, -0.1);
  ctx.lineWidth = Math.max(2, 0.008 * S);
  ctx.lineCap = "round";
  const creases: Pt[][] = [
    [[-0.42, -0.18], [-0.05, -0.26], [0.3, -0.12]],
    [[-0.4, 0.02], [0.0, -0.02], [0.22, 0.12]],
    [[0.2, 0.4], [0.12, 0.05], [0.28, -0.3]],
  ];
  for (const line of creases) {
    ctx.beginPath();
    at(line).forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.stroke();
  }
}

// Who raises the hand, and where they stood in the previous scene.
export function handOwner(spec: Extract<Spec, { type: "hand" }>, prev: Scene | undefined, cast: Character[]) {
  const people = (prev?.actors ?? []).filter(isPerson);
  const person = people.find((p) => p.who === spec.who) ?? people[0];
  const look = lookOf(cast.find((c) => c.id === person?.who));
  return { x: person?.x ?? 0.5, skin: look.skin, sleeve: look.top.color };
}

// The person's palm rises from below on their side of the frame, covers
// the lens at the cut, then sweeps away to the other side.
export function handDraw(frames: number, owner: { x: number; skin: string; sleeve: string }): DrawFn {
  return (ctx, frame, _fps, W, H) => {
    const p = clamp01(frame / frames);
    const cover = 1.12 * Math.max(W / 1.0, H / 1.1);
    const side = owner.x < 0.5 ? -1 : 1;
    let cx: number, cy: number, S: number, rot: number, near: number;
    if (p <= 0.5) {
      const q = p / 0.5;
      const S0 = 0.42 * Math.min(W, H);
      S = approach(S0, cover, q);
      const e = Easing.out(Easing.quad)(q);
      cx = lerp(owner.x * W, W / 2, e);
      cy = lerp(H + 1.3 * S0, H / 2, e);
      rot = 18 * side * (1 - e);
      near = q * q;
    } else {
      const q = (p - 0.5) / 0.5;
      const e = Easing.in(Easing.quad)(q);
      S = cover;
      cx = W / 2 - side * (W / 2 + 1.25 * S) * e;
      cy = H / 2 + 0.1 * H * e;
      rot = -10 * side * e;
      near = 1 - q;
    }
    drawPalm(ctx, cx, cy, S, rot, owner.skin, owner.sleeve, 8900 + boil(frame, 3) * 13, near);
  };
}

// ------------------------------------------------------------ zoom: into a window / a round thing

export type ZoomState = {
  cx: number; // target centre on screen before the zoom
  cy: number;
  tw: number; // target size on screen before the zoom
  th: number;
  layerZoom: number;
  Z: number; // current zoom of the old scene
  Z1: number; // zoom at which the target fills the frame
  ox: number; // where the target centre has moved to
  oy: number;
  inner: number; // scale of the new scene seen through the target
};

// Where the target sits on screen follows the old scene's camera and the
// target's layer depth, exactly as the layer itself is drawn.
export function zoomState(spec: ZoomSpec, cam: CamState, p: number, W: number, H: number): ZoomState {
  const z = 1 + (cam.zoom - 1) * spec.depth;
  const lx = W / 2 + (cam.cx - W / 2) * spec.depth;
  const ly = H / 2 + (cam.cy - H / 2) * spec.depth;
  let cx = W / 2 + z * (spec.x * W - lx);
  let cy = H / 2 + z * (spec.y * H - ly);
  let tw = spec.w * W * z;
  let th = spec.h * H * z;
  if (spec.frame === "window") {
    // fly through the top-left pane, so the window bars slide out of frame
    const pw = tw / 2 - 9 * z;
    const ph = th * 0.48 - 9 * z;
    cx = cx - tw / 2 + pw / 2;
    cy = cy - th / 2 + ph / 2;
    tw = pw;
    th = ph;
  }
  const round = spec.shape === "circle";
  const Z1 = round ? (Math.hypot(W, H) / Math.min(tw, th)) * 1.02 : Math.max(W / tw, H / th) * 1.04;
  const e = Easing.inOut(Easing.cubic)(clamp01(p));
  const Z = Math.pow(Z1, e);
  // the new scene starts just covering the target and grows a little
  // slower than the old one: it is further away, so it reads as depth
  const S0 = round ? Math.min(tw, th) / Math.min(W, H) : Math.max(tw / W, th / H);
  const k = -Math.log(S0) / Math.log(Z1);
  return { cx, cy, tw, th, layerZoom: z, Z, Z1, ox: cx + (W / 2 - cx) * e, oy: cy + (H / 2 - cy) * e, inner: S0 * Math.pow(Z, k) };
}

export const zoomOuterTransform = (z: ZoomState) => `translate(${z.ox}px, ${z.oy}px) scale(${z.Z}) translate(${-z.cx}px, ${-z.cy}px)`;
export const zoomInnerTransform = (z: ZoomState, W: number, H: number) =>
  `translate(${z.ox}px, ${z.oy}px) scale(${z.inner}) translate(${-W / 2}px, ${-H / 2}px)`;

export function zoomClip(spec: ZoomSpec, z: ZoomState) {
  const w = z.tw * z.Z;
  const h = z.th * z.Z;
  if (spec.shape === "circle") return `circle(${Math.min(w, h) / 2}px at ${z.ox}px ${z.oy}px)`;
  return `polygon(${z.ox - w / 2}px ${z.oy - h / 2}px, ${z.ox + w / 2}px ${z.oy - h / 2}px, ${z.ox + w / 2}px ${z.oy + h / 2}px, ${z.ox - w / 2}px ${z.oy + h / 2}px)`;
}

export const prevCamera = (prev: Scene, lead: number, frame: number, fps: number, W: number, H: number) =>
  cameraAt(prev.camera, Math.max(0, prev.duration - lead + frame / fps), prev.duration, W, H);

// The window's wooden frame and bars, redrawn crisp on top while the camera
// flies in (the old scene underneath is only scaled up, so it softens).
export function windowFrameDraw(spec: ZoomSpec, prev: Scene, lead: number, frames: number): DrawFn {
  const wood = PALETTES[prev.backdrop.sky].wood;
  return (ctx, frame, fps, W, H) => {
    const z = zoomState(spec, prevCamera(prev, lead, frame, fps, W, H), clamp01(frame / frames), W, H);
    // the whole window in old-screen coordinates, then through the zoom
    const k = z.layerZoom;
    const gw = spec.w * W * k;
    const gh = spec.h * H * k;
    const gx = z.cx - z.tw / 2;
    const gy = z.cy - z.th / 2;
    const map = (x: number, y: number, w: number, h: number): Pt[] =>
      rectPts(z.ox + (x - z.cx) * z.Z, z.oy + (y - z.cy) * z.Z, w * z.Z, h * z.Z);
    const b = boil(frame, 3);
    const s = k * z.Z;
    const o: PaperOpts = { edge: clamp(3 * s, 3, 14), rough: clamp(2 * s, 2, 8), texture: 0.8, brush: clamp(s / 2, 0.5, 3) };
    const f = 26 * k;
    const parts: [number, number, number, number][] = [
      [gx - f, gy - f, gw + 2 * f, f],
      [gx - f, gy + gh, gw + 2 * f, f],
      [gx - f, gy, f, gh],
      [gx + gw, gy, f, gh],
      [gx + gw / 2 - 9 * k, gy, 18 * k, gh],
      [gx, gy + gh * 0.48 - 9 * k, gw, 18 * k],
      [gx - 44 * k, gy + gh + 16 * k, gw + 88 * k, 26 * k],
    ];
    parts.forEach(([x, y, w, h], i) => paper(ctx, map(x, y, w, h), wood, 7600 + b + i * 11, o));
  };
}

// ------------------------------------------------------------ pull: a hand takes the page away

export type PullState = { gx: number; gy: number; dx: number; dy: number; rot: number; handX: number; handY: number; handAng: number; squeeze: number };

export function pullState(spec: PullSpec, p: number, W: number, H: number): PullState {
  const right = spec.corner !== "top-left";
  const gx = (right ? 0.7 : 0.3) * W; // where the fingers pinch the page
  const gy = 0.2 * H;
  const reach = Easing.out(Easing.cubic)(clamp01(p / 0.32));
  const grip = span(p, 0.3, 0.42);
  const q = Easing.in(Easing.cubic)(clamp01((p - 0.4) / 0.6));
  const dx = (right ? 1 : -1) * 0.3 * W * q;
  const dy = -1.35 * H * q - 14 * grip;
  const rot = (right ? -1 : 1) * (1.5 * grip + 18 * q);
  const ang = right ? 135 : 45; // the fingers point into the page
  const back = ((ang + 180) * Math.PI) / 180;
  const far = (1 - reach) * Math.hypot(W, H) * 0.6;
  return {
    gx, gy, dx, dy, rot,
    handX: gx + dx + Math.cos(back) * far,
    handY: gy + dy + Math.sin(back) * far,
    handAng: ang + rot,
    squeeze: 1 - 0.04 * grip,
  };
}

export const pullTransform = (s: PullState) =>
  `translate(${s.gx + s.dx}px, ${s.gy + s.dy}px) rotate(${s.rot}deg) translate(${-s.gx}px, ${-s.gy}px)`;

function drawPinchHand(ctx: CanvasRenderingContext2D, x: number, y: number, S: number, ang: number, skin: string, sleeve: string, seed: number) {
  // fingertips at (x, y); +u runs along the fingers into the page
  const at = placer(x, y, S, ang);
  const o = big(S);
  paper(ctx, at(capsulePts(-1.3, 0, -5, 0, 0.95)), sleeve, seed + 1, o);
  paper(ctx, at(rectPts(-1.48, -0.52, 0.26, 1.04)), shade(sleeve, -0.1), seed + 2, o);
  paperGroup(
    ctx,
    [
      at(roundRectPts(-1.32, -0.44, 0.9, 0.88, 0.28)),
      ...[-0.3, -0.1, 0.1, 0.3].map((v, i) => at(capsulePts(-0.55, v, -0.06 - (i === 0 || i === 3 ? 0.1 : 0), v * 0.75, 0.2))),
      at(capsulePts(-0.95, 0.4, -0.32, 0.52, 0.21)),
    ],
    skin,
    seed + 3,
    o,
  );
  ctx.strokeStyle = shade(skin, -0.18);
  ctx.lineWidth = Math.max(2, 0.03 * S);
  ctx.lineCap = "round";
  for (const v of [-0.2, 0, 0.2]) {
    const [[x0, y0], [x1, y1]] = at([[-0.5, v], [-0.4, v]]);
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
  }
}

export function pullHandDraw(spec: PullSpec, start: number, frames: number): DrawFn {
  return (ctx, frame, _fps, W, H) => {
    if (frame < start) return;
    const s = pullState(spec, clamp01((frame - start) / frames), W, H);
    const S = 0.34 * Math.min(W, H) * s.squeeze;
    drawPinchHand(ctx, s.handX, s.handY, S, s.handAng, SKINS.tan, "#2b3a8f", 9100 + boil(frame, 3) * 13);
  };
}
