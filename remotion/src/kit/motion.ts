import { Easing } from "remotion";
import type { Enter, Exit, PropAction, PropIdle } from "../types";
import { clamp01, span } from "./camera";
import { rng } from "./paper";

// Prop motion. A paper prop can't bend, so all its acting comes from moving
// the whole piece: hops, rocks, tilts, squashes and flips, pivoting on its
// bottom edge like a puppet on a stick. (People have jointed limbs; see
// src/puppet/pose.ts.)

export type Movable = {
  x: number;
  y: number;
  height: number;
  flip?: boolean;
  enter?: { type: Enter; at?: number };
  exit?: { type: Exit; at: number };
  idle?: PropIdle;
  actions?: PropAction[];
};

// Puppets move "on twos" (12 poses a second at 24fps): the handmade feel.
export const STEP = 1 / 12;
export const onTwos = (t: number) => Math.floor(t / STEP + 1e-6) * STEP;

export type Pose = {
  dx: number; // px
  dy: number; // px, negative = up
  rot: number; // degrees
  sx: number; // negative = mirrored
  sy: number;
  visible: boolean;
};

const outBack = Easing.out(Easing.back(1.7));
const outBounce = Easing.bounce;
const inOut = Easing.inOut(Easing.cubic);

export function poseAt(piece: Movable, aspect: number, tRaw: number, W: number, H: number, seed: number): Pose {
  const t = onTwos(tRaw);
  const pose: Pose = { dx: 0, dy: 0, rot: 0, sx: 1, sy: 1, visible: true };
  const h = piece.height * H;
  const w = h * aspect;
  const phase = rng(seed)() * Math.PI * 2;
  let facing = piece.flip ? -1 : 1;

  // --- enter ---
  const enter = piece.enter?.type ?? "pop";
  const at = piece.enter?.at ?? 0;
  if (enter !== "none") {
    if (t < at) pose.visible = false;
    const e = t - at;
    if (enter === "pop") {
      // unfolds upward like a pop-up book page
      const p = span(e, 0, 0.45, outBack);
      pose.sy *= Math.max(0.001, p);
      pose.sx *= 0.7 + 0.3 * Math.min(1, p);
    } else if (enter === "drop") {
      const p = span(e, 0, 0.55, outBounce);
      pose.dy += -(piece.y * H + 80) * (1 - p);
      const land = span(e, 0.3, 0.55, Easing.linear);
      const squash = Math.sin(land * Math.PI) * 0.12;
      pose.sy *= 1 - squash;
      pose.sx *= 1 + squash;
    } else if (enter === "flip") {
      const p = span(e, 0, 0.4, outBack);
      pose.sx *= Math.max(0.001, p);
    } else {
      // slide in from a side, hopping as it comes
      const from = enter === "slide-left" ? -(piece.x * W + w / 2 + 40) : W - piece.x * W + w / 2 + 40;
      const dur = 1.0;
      const p = span(e, 0, dur, Easing.out(Easing.quad));
      pose.dx += from * (1 - p);
      if (e >= 0 && e < dur) {
        const steps = (e / dur) * 4;
        pose.dy -= Math.abs(Math.sin(steps * Math.PI)) * 22;
        pose.rot += Math.sin(steps * Math.PI) * 5 * (enter === "slide-left" ? 1 : -1);
      }
    }
  }

  // --- idle (always running underneath) ---
  const idle = piece.idle ?? "breathe";
  if (idle === "breathe") {
    const s = Math.sin((t / 2.6) * Math.PI * 2 + phase);
    pose.sy *= 1 + 0.014 * s;
    pose.sx *= 1 - 0.006 * s;
  } else if (idle === "sway") {
    pose.rot += 1.8 * Math.sin((t / 3.2) * Math.PI * 2 + phase);
  } else if (idle === "float") {
    pose.dy += 12 * Math.sin((t / 2.8) * Math.PI * 2 + phase);
    pose.rot += 1.2 * Math.sin((t / 4.1) * Math.PI * 2 + phase);
  }

  // --- actions, in time order; walks and turns persist ---
  const actions = [...(piece.actions ?? [])].sort((a, b) => a.at - b.at);
  let x = piece.x;
  for (const a of actions) {
    const e = t - a.at;
    if (e < 0) continue;
    switch (a.do) {
      case "walk": {
        const p = span(e, 0, a.dur, Easing.inOut(Easing.sin));
        pose.dx += (a.to - x) * W * p;
        if (e < a.dur) {
          const steps = (e / a.dur) * Math.max(2, Math.round(a.dur * 3));
          pose.dy -= Math.abs(Math.sin(steps * Math.PI)) * 16;
          pose.rot += Math.sin(steps * Math.PI) * 4;
        }
        if (e >= a.dur) x = a.to; // later walks start from here
        break;
      }
      case "turn": {
        const p = span(e, 0, 0.25, inOut);
        const flipNow = Math.cos(p * Math.PI); // 1 -> -1
        pose.dy -= Math.sin(p * Math.PI) * 10;
        if (p >= 1) facing = -facing;
        else pose.sx *= flipNow;
        break;
      }
      case "hop": {
        const d = 0.45;
        if (e < d) {
          const p = e / d;
          pose.dy -= Math.sin(p * Math.PI) * h * 0.12;
          const squash = p < 0.15 ? (0.15 - p) * 0.6 : p > 0.85 ? (p - 0.85) * 0.6 : -0.04;
          pose.sy *= 1 - squash;
          pose.sx *= 1 + squash * 0.6;
        }
        break;
      }
      case "talk": {
        if (e < a.dur) {
          // quick little bobs and tilts in speech rhythm
          const beat = Math.sin(e * Math.PI * 2 * 3.1);
          pose.dy -= Math.max(0, beat) * 7;
          pose.rot += Math.sin(e * Math.PI * 2 * 1.7) * 2.2;
          pose.sy *= 1 + 0.018 * beat;
        }
        break;
      }
      case "shake": {
        const d = a.dur ?? 0.6;
        if (e < d) pose.rot += Math.sin(e * Math.PI * 2 * 9) * 4 * (1 - e / d);
        break;
      }
      case "nod": {
        const d = 0.7;
        if (e < d) pose.rot += Math.sin((e / d) * Math.PI * 4) * 4 * facing * (1 - e / d);
        break;
      }
      case "tilt": {
        // lean over on the base and stay there (a tower sinking, a tree falling)
        pose.rot += (a.deg ?? 8) * span(e, 0, 0.7, Easing.inOut(Easing.cubic));
        break;
      }
      case "grow": {
        const d = a.dur ?? 0.8;
        if (e < d) {
          const p = Math.sin(clamp01(e / d) * Math.PI);
          pose.sx *= 1 + 0.14 * p;
          pose.sy *= 1 + 0.14 * p;
        }
        break;
      }
    }
  }
  pose.sx *= facing;

  // --- exit ---
  if (piece.exit) {
    const e = t - piece.exit.at;
    if (e >= 0) {
      const type = piece.exit.type;
      if (type === "fold") {
        const p = span(e, 0, 0.35, Easing.in(Easing.back(1.5)));
        pose.sy *= Math.max(0.001, 1 - p);
        if (p >= 1) pose.visible = false;
      } else if (type === "fly-up") {
        const p = span(e, 0, 0.6, Easing.in(Easing.quad));
        pose.dy -= p * (piece.y * H + 200);
        pose.rot += p * 20;
        if (p >= 1) pose.visible = false;
      } else {
        const toLeft = type === "slide-left";
        const dist = toLeft ? -(x * W + w / 2 + 40) : W - x * W + w / 2 + 40;
        const dur = 1.0;
        const p = span(e, 0, dur, Easing.in(Easing.quad));
        pose.dx += dist * p;
        if (e < dur) {
          const steps = (e / dur) * 4;
          pose.dy -= Math.abs(Math.sin(steps * Math.PI)) * 22;
        }
        if (p >= 1) pose.visible = false;
      }
    }
  }

  // --- boil: the piece is re-placed by hand every 3 frames ---
  const b = rng(seed * 7919 + Math.floor(tRaw * 8));
  pose.dx += (b() - 0.5) * 1.6;
  pose.dy += (b() - 0.5) * 1.6;
  pose.rot += (b() - 0.5) * 0.5;

  return pose;
}
