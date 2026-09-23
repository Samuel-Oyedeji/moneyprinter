import React, { useLayoutEffect, useRef, useState } from "react";
import { continueRender, delayRender, useCurrentFrame, useVideoConfig } from "remotion";
import { fontsReady } from "./fonts";

export type DrawFn = (ctx: CanvasRenderingContext2D, frame: number, fps: number, w: number, h: number) => void;

// Extra canvas around the frame so camera pans and parallax never show an edge.
export const OVERSCAN = 160;

// Waits for fonts, then calls `draw` once per frame in frame coordinates
// (0,0 = top-left of the visible frame; the overscan margin is negative space).
export const PaperCanvas: React.FC<{ draw: DrawFn; overscan?: number; style?: React.CSSProperties }> = ({
  draw,
  overscan = OVERSCAN,
  style,
}) => {
  const ref = useRef<HTMLCanvasElement>(null);
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const [handle] = useState(() => delayRender("paper-canvas"));
  const [ready, setReady] = useState(false);

  useLayoutEffect(() => {
    fontsReady().then(() => setReady(true));
  }, []);

  useLayoutEffect(() => {
    if (!ready || !ref.current) return;
    const ctx = ref.current.getContext("2d")!;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width + overscan * 2, height + overscan * 2);
    ctx.translate(overscan, overscan);
    draw(ctx, frame, fps, width, height);
    continueRender(handle);
  }, [frame, ready, draw, fps, width, height, overscan, handle]);

  return (
    <canvas
      ref={ref}
      width={width + overscan * 2}
      height={height + overscan * 2}
      style={{ position: "absolute", left: -overscan, top: -overscan, ...style }}
    />
  );
};
