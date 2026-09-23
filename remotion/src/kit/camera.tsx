import React, { createContext, useContext } from "react";
import { Easing, interpolate } from "remotion";
import type { Camera } from "../types";

// The camera looks at a point (cx, cy) with a zoom. Each layer follows it by
// its depth: depth 1 moves fully with the camera, depth 0.1 (the sky) barely
// moves, depth > 1 (foreground) moves more. That spread is the parallax.

export type CamState = { cx: number; cy: number; zoom: number };

const ease = Easing.inOut(Easing.cubic);

export function cameraAt(cam: Camera | undefined, t: number, duration: number, W: number, H: number): CamState {
  const move = cam?.move ?? "drift";
  const k = cam?.amount ?? 1;
  const p = ease(Math.min(1, Math.max(0, t / Math.max(0.01, duration))));
  const fx = (cam?.focusX ?? 0.5) * W;
  const fy = (cam?.focusY ?? 0.45) * H;
  const mid = { cx: W / 2, cy: H / 2 };
  const lerp = (a: number, b: number) => a + (b - a) * p;

  switch (move) {
    case "push": {
      // ease toward the focus point while zooming in
      const z = 1 + 0.14 * k;
      return { cx: lerp(mid.cx, mid.cx + (fx - mid.cx) * 0.5), cy: lerp(mid.cy, mid.cy + (fy - mid.cy) * 0.5), zoom: lerp(1, z) };
    }
    case "pull": {
      const z = 1 + 0.14 * k;
      return { cx: lerp(mid.cx + (fx - mid.cx) * 0.5, mid.cx), cy: lerp(mid.cy + (fy - mid.cy) * 0.5, mid.cy), zoom: lerp(z, 1) };
    }
    case "pan-left":
      return { cx: lerp(mid.cx + 90 * k, mid.cx - 90 * k), cy: mid.cy, zoom: 1.04 };
    case "pan-right":
      return { cx: lerp(mid.cx - 90 * k, mid.cx + 90 * k), cy: mid.cy, zoom: 1.04 };
    case "rise":
      return { cx: mid.cx, cy: lerp(mid.cy + 110 * k, mid.cy - 40 * k), zoom: 1.05 };
    case "drift":
      // the gentle default: a slow push with a little sideways travel
      return { cx: lerp(mid.cx - 20 * k, mid.cx + 20 * k), cy: mid.cy, zoom: lerp(1, 1 + 0.05 * k) };
    case "still":
    default:
      return { ...mid, zoom: 1 };
  }
}

export const CamContext = createContext<CamState>({ cx: 540, cy: 960, zoom: 1 });

export function layerTransform(cam: CamState, depth: number, W: number, H: number) {
  const z = 1 + (cam.zoom - 1) * depth;
  const cx = W / 2 + (cam.cx - W / 2) * depth;
  const cy = H / 2 + (cam.cy - H / 2) * depth;
  return `translate(${W / 2}px, ${H / 2}px) scale(${z}) translate(${-cx}px, ${-cy}px)`;
}

// One depth plane. Everything inside is drawn in frame coordinates.
export const Layer: React.FC<{ depth: number; W: number; H: number; children: React.ReactNode }> = ({ depth, W, H, children }) => {
  const cam = useContext(CamContext);
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: W,
        height: H,
        transformOrigin: "0 0",
        transform: layerTransform(cam, depth, W, H),
      }}
    >
      {children}
    </div>
  );
};

// Small helpers shared by motion code.
export const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
export const span = (t: number, a: number, b: number, easing = ease) =>
  interpolate(t, [a, b], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing });
