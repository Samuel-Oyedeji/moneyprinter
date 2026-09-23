import React, { useMemo } from "react";
import { AbsoluteFill } from "remotion";
import { DrawFn, PaperCanvas } from "../kit/PaperCanvas";
import { boil, rng } from "../kit/paper";

// A sheet of paper fibre over the whole frame. It ties the code-drawn paper
// and the AI cut-outs together, and it shifts a little with the boil the
// way a re-photographed stop-motion frame would.

let sheet: HTMLCanvasElement | null = null;

function fibreSheet(W: number, H: number) {
  if (sheet && sheet.width === W + 40) return sheet;
  sheet = document.createElement("canvas");
  sheet.width = W + 40;
  sheet.height = H + 40;
  const ctx = sheet.getContext("2d")!;
  ctx.fillStyle = "rgb(128,128,128)";
  ctx.fillRect(0, 0, sheet.width, sheet.height);
  const r = rng(4242);
  // soft blotches
  for (let i = 0; i < 90; i++) {
    const v = 128 + (r() - 0.5) * 22;
    ctx.fillStyle = `rgba(${v},${v},${v},0.35)`;
    ctx.beginPath();
    ctx.arc(r() * sheet.width, r() * sheet.height, 40 + r() * 160, 0, Math.PI * 2);
    ctx.fill();
  }
  // fibres
  ctx.lineCap = "round";
  for (let i = 0; i < 9000; i++) {
    const x = r() * sheet.width;
    const y = r() * sheet.height;
    const a = r() * Math.PI * 2;
    const len = 3 + r() * 14;
    const v = r() < 0.5 ? 90 + r() * 30 : 170 + r() * 40;
    ctx.strokeStyle = `rgba(${v},${v},${v},${0.25 + r() * 0.35})`;
    ctx.lineWidth = 0.6 + r() * 1.2;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.quadraticCurveTo(x + Math.cos(a + 0.6) * len * 0.5, y + Math.sin(a + 0.6) * len * 0.5, x + Math.cos(a) * len, y + Math.sin(a) * len);
    ctx.stroke();
  }
  return sheet;
}

export const Grain: React.FC<{ strength?: number }> = ({ strength = 0.5 }) => {
  const draw: DrawFn = useMemo(
    () => (ctx, frame, fps, W, H) => {
      const r = rng(boil(frame, 3) + 17);
      ctx.drawImage(fibreSheet(W, H), -Math.floor(r() * 40), -Math.floor(r() * 40));
    },
    [],
  );
  return (
    <>
      <AbsoluteFill style={{ mixBlendMode: "overlay", opacity: strength, pointerEvents: "none" }}>
        <PaperCanvas draw={draw} overscan={0} />
      </AbsoluteFill>
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 55%, rgba(30,15,10,0.28) 100%)",
        }}
      />
    </>
  );
};
