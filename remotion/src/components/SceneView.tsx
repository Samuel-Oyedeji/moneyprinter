import React, { useMemo } from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Character, Scene } from "../types";
import { buildPlanes, Planes } from "./Backdrop";
import { Actors } from "./Actors";
import { Notes } from "./Notes";
import { CamContext, cameraAt, Layer } from "../kit/camera";
import { PALETTES } from "../kit/palettes";
import { DrawFn, PaperCanvas } from "../kit/PaperCanvas";
import { boil, rng, PAPER } from "../kit/paper";

// The torn edge that sweeps up the frame when a scene arrives: the old page
// is ripped away upward, revealing the new one underneath.
function tearEdge(p: number, x: number, W: number, H: number, jag: number[]) {
  const i = Math.min(jag.length - 1, Math.max(0, Math.round((x / W) * (jag.length - 1))));
  const base = H * (1.1 - 1.25 * p);
  return base + ((x - W / 2) / W) * 160 + jag[i];
}

function useJag(seed: number) {
  return useMemo(() => {
    const r = rng(seed);
    return Array.from({ length: 61 }, () => (r() - 0.5) * 26);
  }, [seed]);
}

export const SceneView: React.FC<{ scene: Scene; cast: Character[]; index: number; lead: number; wipe: number }> = ({ scene, cast, index, lead, wipe }) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  const t = frame / fps - lead;
  const cam = cameraAt(scene.camera, Math.max(0, t), scene.duration, W, H);
  const { back, front } = useMemo(() => buildPlanes(scene.backdrop, lead), [scene.backdrop, lead]);
  const notes = scene.notes ?? [];
  const jag = useJag(index * 31 + 7);

  // wipe progress: 0 = scene hidden below the frame, 1 = fully shown
  const p = wipe > 0 ? interpolate(frame, [0, wipe], [0, 1], { extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) }) : 1;
  const clip =
    p < 1
      ? `polygon(${Array.from({ length: 31 }, (_, k) => {
          const x = (k / 30) * W;
          return `${x}px ${tearEdge(p, x, W, H, jag)}px`;
        }).join(", ")}, ${W}px ${H}px, 0px ${H}px)`
      : undefined;

  const edgeDraw: DrawFn = useMemo(
    () => (ctx, f, _fps, w, h) => {
      const pp = wipe > 0 ? interpolate(f, [0, wipe], [0, 1], { extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) }) : 1;
      if (pp <= 0 || pp >= 1) return;
      const r = rng(boil(f, 3) + 400);
      const line = (off: number, amp: number) => {
        for (let k = 0; k <= 60; k++) {
          const x = (k / 60) * w;
          const y = tearEdge(pp, x, w, h, jag) + off + (r() - 0.5) * amp;
          if (k === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
      };
      // shadow of the old page on the new one
      ctx.beginPath();
      line(0, 0);
      ctx.lineTo(w, h * 2);
      ctx.lineTo(0, h * 2);
      ctx.closePath();
      const g = ctx.createLinearGradient(0, tearEdge(pp, w / 2, w, h, jag), 0, tearEdge(pp, w / 2, w, h, jag) + 60);
      g.addColorStop(0, "rgba(10,10,40,0.35)");
      g.addColorStop(1, "rgba(10,10,40,0)");
      ctx.fillStyle = g;
      ctx.fill();
      // the fibrous cream torn edge of the old page
      ctx.beginPath();
      line(-4, 10);
      for (let k = 60; k >= 0; k--) {
        const x = (k / 60) * w;
        ctx.lineTo(x, tearEdge(pp, x, w, h, jag) - 22 + (r() - 0.5) * 12);
      }
      ctx.closePath();
      ctx.fillStyle = PAPER;
      ctx.fill();
    },
    [wipe, jag],
  );

  const sky = scene.backdrop.sky;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ clipPath: clip, overflow: "hidden", backgroundColor: PALETTES[sky].sky }}>
        <CamContext.Provider value={cam}>
          <Planes planes={back} lead={lead} W={W} H={H} />
          <Actors actors={scene.actors ?? []} cast={cast} sceneIndex={index} lead={lead} W={W} H={H} />
          <Layer depth={1} W={W} H={H}>
            <Notes notes={notes} sky={sky} lead={lead} space="world" />
          </Layer>
          <Planes planes={front} lead={lead} W={W} H={H} />
        </CamContext.Provider>
        <Notes notes={notes} sky={sky} lead={lead} space="screen" />
      </AbsoluteFill>
      {wipe > 0 && frame <= wipe ? <PaperCanvas draw={edgeDraw} overscan={0} /> : null}
    </AbsoluteFill>
  );
};
