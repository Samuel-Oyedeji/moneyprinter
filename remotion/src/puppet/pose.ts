import { Easing } from "remotion";
import type { Expression, Person } from "../types";
import { span } from "../kit/camera";
import { onTwos } from "../kit/motion";
import { rng } from "../kit/paper";
import type { Body } from "./character";

// A person's pose at one moment: where the puppet stands and how each joint
// is turned. Everything is in the "facing right" frame; facing left is the
// same drawing mirrored. Limb angles are degrees: 0 = hanging straight
// down, +90 = pointing forward (the way they face), 180 = straight up.

export type Limb = { up: number; lo: number };
export type Mouth = "smile" | "grin" | "neutral" | "frown" | "o" | "wavy" | "talk1" | "talk2";
export type Eyes = "normal" | "wide" | "happy" | "sleepy" | "closed";
export type Brows = "neutral" | "raised" | "worried" | "angry";

export type PuppetPose = {
  x: number; // frame fraction
  dy: number; // px
  jx: number; // boil jitter, px
  lean: number; // degrees
  sx: number; // includes mirroring for facing left
  sy: number;
  visible: boolean;
  front: boolean;
  armB: Limb; // back arm (away from where they face)
  armF: Limb; // front arm: points, waves, holds things
  legB: Limb;
  legF: Limb;
  headTilt: number;
  headDx: number; // fraction of height
  lookX: number;
  lookY: number;
  eyes: Eyes;
  mouth: Mouth;
  brows: Brows;
  holdUp: boolean;
};

const FACES: Record<Expression, { mouth: Mouth; eyes: Eyes; brows: Brows }> = {
  smile: { mouth: "smile", eyes: "normal", brows: "neutral" },
  grin: { mouth: "grin", eyes: "happy", brows: "raised" },
  neutral: { mouth: "neutral", eyes: "normal", brows: "neutral" },
  frown: { mouth: "frown", eyes: "normal", brows: "worried" },
  surprised: { mouth: "o", eyes: "wide", brows: "raised" },
  worried: { mouth: "wavy", eyes: "normal", brows: "worried" },
  angry: { mouth: "frown", eyes: "normal", brows: "angry" },
  sleepy: { mouth: "neutral", eyes: "sleepy", brows: "neutral" },
};

const WALK_SPEED = 0.38; // frame widths per second
const CYCLE = 0.8; // seconds per two steps

const lerp = (a: number, b: number, w: number) => a + (b - a) * w;
const mixLimb = (a: Limb, b: Limb, w: number): Limb => ({ up: lerp(a.up, b.up, w), lo: lerp(a.lo, b.lo, w) });
const DEG = 180 / Math.PI;

// weight of an action over its life: ease in, hold, ease out
function weight(e: number, dur: number, fade = 0.2) {
  if (e < 0 || e > dur) return 0;
  return Math.min(span(e, 0, fade), 1 - span(e, dur - fade, dur));
}

// Two-joint arm reaching for a point; returns the elbow-down solution.
export function reach(sx: number, sy: number, tx: number, ty: number, l1: number, l2: number): Limb {
  const dx = tx - sx, dy = ty - sy;
  const d = Math.min(Math.hypot(dx, dy), (l1 + l2) * 0.999);
  const base = Math.atan2(dx, dy); // angle from "down"
  const a = Math.acos(Math.max(-1, Math.min(1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))));
  const pick = (up: number) => {
    const ex = sx + Math.sin(up) * l1, ey = sy + Math.cos(up) * l1;
    return { up, lo: Math.atan2(tx - ex, ty - ey), ey };
  };
  const s1 = pick(base + a), s2 = pick(base - a);
  const s = s1.ey > s2.ey ? s1 : s2;
  return { up: s.up * DEG, lo: s.lo * DEG };
}

type Walk = { from: number; to: number; at: number; dur: number };

export function personPose(p: Person, body: Body, tRaw: number, seed: number): PuppetPose {
  const t = onTwos(tRaw);
  const r0 = rng(seed);
  const phase = r0() * 10;
  const front = p.facing === "front";
  let facing = p.facing === "left" ? -1 : 1;
  let face: Expression = p.face ?? "smile";

  const pose: PuppetPose = {
    x: p.x, dy: 0, jx: 0, lean: body.lean, sx: 1, sy: 1, visible: true, front,
    armB: { up: -7, lo: -3 }, armF: { up: 7, lo: 3 },
    legB: { up: -2, lo: -2 }, legF: { up: 2, lo: 2 },
    headTilt: 0, headDx: 0, lookX: 0, lookY: 0,
    eyes: "normal", mouth: "smile", brows: "neutral", holdUp: p.holding?.pose === "up",
  };

  // --- idle: breathing sway and blinks
  pose.armF.up += 2 * Math.sin(t * 1.9 + phase);
  pose.armB.up -= 2 * Math.sin(t * 1.9 + phase + 0.6);
  pose.dy += Math.sin(t * 2.4 + phase) * 1.2;

  // --- all the walking this person does: entrance, walks, exit. Each walk
  // starts where the last one ended.
  const enter = p.enter?.type ?? "pop";
  const enterAt = p.enter?.at ?? 0;
  const slideIn = enter === "slide-left" || enter === "slide-right";
  const actions = [...(p.actions ?? [])].sort((a, b) => a.at - b.at);
  const plan: { to: number; at: number; dur?: number; entrance?: boolean }[] = [];
  if (slideIn) plan.push({ to: p.x, at: enterAt, entrance: true });
  for (const a of actions) if (a.do === "walk") plan.push({ to: a.to, at: a.at, dur: a.dur });
  if (p.exit?.type === "slide-left" || p.exit?.type === "slide-right") {
    plan.push({ to: p.exit.type === "slide-left" ? -0.2 : 1.2, at: p.exit.at });
  }
  plan.sort((a, b) => a.at - b.at);
  const start = slideIn ? (enter === "slide-left" ? -0.18 : 1.18) : p.x;
  const walks: (Walk & { entrance?: boolean })[] = [];
  let cur = start;
  for (const w of plan) {
    const dur = Math.max(0.3, w.dur ?? Math.abs(w.to - cur) / WALK_SPEED);
    walks.push({ from: cur, to: w.to, at: w.at, dur, entrance: w.entrance });
    cur = w.to;
  }

  // facing changes, applied in time order: walks face where they go, a
  // finished entrance settles into the requested facing, turns flip
  const facingEvents: { at: number; set?: number; flip?: boolean }[] = [];
  for (const w of walks) {
    if (w.to !== w.from) facingEvents.push({ at: w.at, set: w.to > w.from ? 1 : -1 });
    if (w.entrance && p.facing && p.facing !== "front") facingEvents.push({ at: w.at + w.dur, set: p.facing === "left" ? -1 : 1 });
  }
  for (const a of actions) if (a.do === "turn") facingEvents.push({ at: a.at + 0.125, flip: true });
  facingEvents.sort((a, b) => a.at - b.at);
  for (const ev of facingEvents) {
    if (t < ev.at) break;
    facing = ev.flip ? -facing : ev.set!;
  }

  let x = start;
  let walking = 0; // 0..1 blend of the walk cycle
  let walkE = 0;
  for (const w of walks) {
    const e = t - w.at;
    if (e < 0) break;
    x = lerp(w.from, w.to, span(e, 0, w.dur, Easing.inOut(Easing.sin)));
    if (e < w.dur) {
      walking = Math.max(walking, Math.min(1, Math.min(e, w.dur - e) / 0.15));
      walkE = e;
    }
  }
  pose.x = x;
  if (slideIn && t < enterAt) pose.visible = false;

  if (walking > 0) {
    const ph = (walkE / CYCLE) * Math.PI * 2;
    const s = Math.sin(ph);
    const legSwing = (sgn: number): Limb => {
      const up = 24 * s * sgn;
      return { up, lo: up - 22 * Math.max(0, -s * sgn) };
    };
    pose.legF = mixLimb(pose.legF, legSwing(1), walking);
    pose.legB = mixLimb(pose.legB, legSwing(-1), walking);
    pose.armF = mixLimb(pose.armF, { up: 6 - 20 * s, lo: 14 - 20 * s }, walking);
    pose.armB = mixLimb(pose.armB, { up: -6 + 20 * s, lo: 4 + 20 * s }, walking);
    pose.lean += 3 * walking;
  }
  const bob = walking > 0 ? Math.abs(Math.cos((walkE / CYCLE) * Math.PI * 2)) * walking : 0;

  // --- enter / exit that aren't walks
  if (enter === "pop") {
    const k = span(t - enterAt, 0, 0.45, Easing.out(Easing.back(1.7)));
    if (t < enterAt) pose.visible = false;
    pose.sy *= Math.max(0.001, k);
  } else if (enter === "drop") {
    if (t < enterAt) pose.visible = false;
    const k = span(t - enterAt, 0, 0.55, Easing.bounce);
    pose.dy -= (1 - k) * 900;
  } else if (enter === "flip") {
    if (t < enterAt) pose.visible = false;
    pose.sx *= Math.max(0.001, span(t - enterAt, 0, 0.4, Easing.out(Easing.back(1.7))));
  }
  if (p.exit) {
    const e = t - p.exit.at;
    if (p.exit.type === "fold" && e >= 0) {
      const k = span(e, 0, 0.35, Easing.in(Easing.back(1.5)));
      pose.sy *= Math.max(0.001, 1 - k);
      if (k >= 1) pose.visible = false;
    } else if (p.exit.type === "fly-up" && e >= 0) {
      const k = span(e, 0, 0.6, Easing.in(Easing.quad));
      pose.dy -= k * 1400;
      if (k >= 1) pose.visible = false;
    } else if (e >= 0) {
      const last = walks[walks.length - 1];
      if (last && t >= last.at + last.dur) pose.visible = false;
    }
  }

  // --- gestures
  let mouthOverride: Mouth | null = null;
  let eyesOverride: Eyes | null = null;
  let browsOverride: Brows | null = null;
  const shX = body.sh * 0.92, shY = body.shoulderY + 0.02;
  for (const a of actions) {
    const e = t - a.at;
    if (e < 0) continue;
    switch (a.do) {
      case "talk": {
        const w = weight(e, a.dur, 0.1);
        if (w > 0) {
          const beat = rng(seed * 31 + Math.floor(e * 12))();
          mouthOverride = beat < 0.3 ? "talk2" : beat < 0.75 ? "talk1" : null;
          pose.headTilt += 2.5 * Math.sin(e * 8.2) * w;
          const g = 0.5 + 0.5 * Math.sin(e * 5.2);
          pose.armF = mixLimb(pose.armF, { up: 22, lo: 70 + 30 * g }, w * 0.8);
        }
        break;
      }
      case "point": {
        const w = weight(e, a.dur ?? 1.4, 0.2);
        pose.armF = mixLimb(pose.armF, { up: 78, lo: 84 }, w);
        break;
      }
      case "wave": {
        const w = weight(e, a.dur ?? 1.4, 0.2);
        pose.armF = mixLimb(pose.armF, { up: 150, lo: 172 + 24 * Math.sin(e * 14) }, w);
        if (w > 0.5) mouthOverride = "grin";
        break;
      }
      case "shrug": {
        const w = weight(e, 1.0, 0.2);
        pose.armF = mixLimb(pose.armF, { up: 28, lo: 105 }, w);
        pose.armB = mixLimb(pose.armB, { up: -28, lo: -105 }, w);
        pose.headTilt += 7 * w;
        if (w > 0.3) { mouthOverride = "neutral"; browsOverride = "raised"; }
        break;
      }
      case "think": {
        const w = weight(e, a.dur ?? 1.6, 0.25);
        const chinX = 0.035 + body.headR * 0.25, chinY = body.headCY + body.headR * 0.95;
        pose.armF = mixLimb(pose.armF, reach(shX, shY, chinX, chinY, body.armUp, body.armLo + body.handR * 0.5), w);
        if (w > 0.3) { pose.lookX = lerp(pose.lookX, 0.5, w); pose.lookY = lerp(pose.lookY, -1, w); mouthOverride = "neutral"; }
        break;
      }
      case "cheer": {
        const d = a.dur ?? 1.1;
        const w = weight(e, d, 0.15);
        pose.armF = mixLimb(pose.armF, { up: 150, lo: 165 }, w);
        pose.armB = mixLimb(pose.armB, { up: -150, lo: -165 }, w);
        if (e < 0.45) pose.dy -= Math.sin((e / 0.45) * Math.PI) * 60;
        if (w > 0.2) { mouthOverride = "grin"; eyesOverride = "happy"; }
        break;
      }
      case "nod": {
        if (e < 0.7) pose.headTilt += 10 * Math.abs(Math.sin((e / 0.7) * Math.PI * 2)) * (1 - e / 0.7);
        break;
      }
      case "shake-head": {
        if (e < 0.8) {
          const k = Math.sin((e / 0.8) * Math.PI * 6) * (1 - e / 0.8);
          pose.headDx += 0.02 * k;
          pose.lookX = -k;
        }
        break;
      }
      case "hop": {
        if (e < 0.45) {
          const k = Math.sin((e / 0.45) * Math.PI);
          pose.dy -= k * 70;
          pose.legF.lo -= 35 * k;
          pose.legB.lo -= 35 * k;
          pose.armF.up += 30 * k;
          pose.armB.up -= 30 * k;
        }
        break;
      }
      case "turn": {
        const k = span(e, 0, 0.25, Easing.inOut(Easing.cubic));
        if (k < 1) pose.sx *= Math.max(0.06, Math.abs(Math.cos(k * Math.PI)));
        break;
      }
      case "look": {
        const dirs = { left: [-1, 0], right: [1, 0], up: [0.3, -1], down: [0.3, 1], ahead: [0, 0] } as const;
        [pose.lookX, pose.lookY] = dirs[a.dir];
        break;
      }
      case "feel":
        face = a.face;
        break;
    }
  }

  // holding something up to look at it
  if (pose.holdUp) {
    const tx = body.sh + 0.12, ty = body.headCY + body.headR * 1.25;
    pose.armF = mixLimb(pose.armF, reach(shX, shY, tx, ty, body.armUp, body.armLo), 1);
    if (pose.lookX === 0 && pose.lookY === 0) {
      pose.lookX = 0.5;
      pose.lookY = 0.5;
    }
  }

  const f = FACES[face];
  pose.mouth = mouthOverride ?? f.mouth;
  pose.eyes = eyesOverride ?? f.eyes;
  pose.brows = browsOverride ?? f.brows;

  // blink every few seconds (skipped while eyes are doing something else)
  const every = 3.1 + r0() * 1.4;
  if (pose.eyes === "normal" && (t + phase) % every < 0.13) pose.eyes = "closed";

  pose.dy -= bob * 14;
  // boil: re-placed by hand every 3 frames
  const b = rng(seed * 7919 + Math.floor(tRaw * 8));
  pose.jx = (b() - 0.5) * 1.6;
  pose.dy += (b() - 0.5) * 1.6;
  pose.lean += (b() - 0.5) * 0.4;
  pose.sx *= front ? 1 : facing;
  return pose;
}
