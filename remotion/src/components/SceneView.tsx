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
import {
  flyDraw,
  handDraw,
  handOwner,
  prevCamera,
  pullHandDraw,
  pullState,
  pullTransform,
  windowFrameDraw,
  zoomClip,
  zoomInnerTransform,
  zoomOuterTransform,
  zoomState,
} from "./Transitions";
import type { Spec } from "./Transitions";

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

// How this scene arrives (enter) and leaves (exit). Frames are local to the
// scene's Sequence, which starts `lead` seconds before the scene itself.
export type EnterInfo = { spec: Spec; frames: number; prev?: Scene };
export type ExitInfo = { spec: Spec; frames: number; start: number };

const HIDDEN = "inset(0 0 100% 0)";

export const SceneView: React.FC<{ scene: Scene; cast: Character[]; index: number; lead: number; enter: EnterInfo | null; exit: ExitInfo | null }> = ({
  scene,
  cast,
  index,
  lead,
  enter,
  exit,
}) => {
  const frame = useCurrentFrame();
  const { fps, width: W, height: H } = useVideoConfig();
  const t = frame / fps - lead;
  const cam = cameraAt(scene.camera, Math.max(0, t), scene.duration, W, H);
  const { back, front } = useMemo(() => buildPlanes(scene.backdrop, lead), [scene.backdrop, lead]);
  const notes = scene.notes ?? [];
  const jag = useJag(index * 31 + 7);
  const wipe = enter?.spec.type === "tear" ? enter.frames : 0;

  // ---- arriving
  const entering = !!enter && frame <= enter.frames;
  const pIn = enter ? Math.min(1, frame / enter.frames) : 1;
  let clip: string | undefined;
  let inner: string | undefined;
  if (entering && enter) {
    const spec = enter.spec;
    if (spec.type === "tear") {
      // wipe progress: 0 = scene hidden below the frame, 1 = fully shown
      const p = interpolate(frame, [0, wipe], [0, 1], { extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) });
      clip =
        p < 1
          ? `polygon(${Array.from({ length: 31 }, (_, k) => {
              const x = (k / 30) * W;
              return `${x}px ${tearEdge(p, x, W, H, jag)}px`;
            }).join(", ")}, ${W}px ${H}px, 0px ${H}px)`
          : undefined;
    } else if (spec.type === "fly" || spec.type === "hand") {
      if (pIn < 0.5) clip = HIDDEN; // revealed under the carrier, while it fills the frame
    } else if (spec.type === "zoom" && enter.prev) {
      const z = zoomState(spec, prevCamera(enter.prev, lead, frame, fps, W, H), pIn, W, H);
      clip = zoomClip(spec, z);
      inner = zoomInnerTransform(z, W, H);
    }
  }

  // ---- leaving
  const leaving = !!exit && frame >= exit.start;
  const pOut = exit ? Math.min(1, Math.max(0, (frame - exit.start) / exit.frames)) : 0;
  let outer: string | undefined;
  let pulled = false;
  if (leaving && exit) {
    if (exit.spec.type === "zoom") outer = zoomOuterTransform(zoomState(exit.spec, cam, pOut, W, H));
    if (exit.spec.type === "pull") {
      outer = pullTransform(pullState(exit.spec, pOut, W, H));
      pulled = true;
    }
  }

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

  // whatever is drawn over the join: the torn edge, the bird, the hand, the window frame
  const enterOverlay: DrawFn | null = useMemo(() => {
    if (!enter) return null;
    const spec = enter.spec;
    if (spec.type === "tear") return edgeDraw;
    if (spec.type === "fly") return flyDraw(spec, enter.frames);
    if (spec.type === "hand") return handDraw(enter.frames, handOwner(spec, enter.prev, cast));
    if (spec.type === "zoom" && spec.frame === "window" && enter.prev) return windowFrameDraw(spec, enter.prev, lead, enter.frames);
    return null;
  }, [enter, edgeDraw, cast, lead]);
  const exitOverlay: DrawFn | null = useMemo(
    () => (exit?.spec.type === "pull" ? pullHandDraw(exit.spec, exit.start, exit.frames) : null),
    [exit],
  );

  const sky = scene.backdrop.sky;
  return (
    <AbsoluteFill style={{ zIndex: pulled ? 2 : undefined }}>
      <AbsoluteFill style={{ transform: outer, transformOrigin: "0 0" }}>
        <AbsoluteFill
          style={{
            clipPath: clip,
            overflow: "hidden",
            backgroundColor: PALETTES[sky].sky,
            // the page being pulled away: a cream edge and its shadow on the next scene
            boxShadow: pulled ? "0 40px 90px rgba(10,10,40,0.5)" : undefined,
            outline: pulled ? `10px solid ${PAPER}` : undefined,
            outlineOffset: pulled ? -10 : undefined,
          }}
        >
          <AbsoluteFill style={{ transform: inner, transformOrigin: "0 0" }}>
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
        </AbsoluteFill>
      </AbsoluteFill>
      {entering && enterOverlay ? <PaperCanvas draw={enterOverlay} overscan={0} /> : null}
      {leaving && exitOverlay ? <PaperCanvas draw={exitOverlay} overscan={0} /> : null}
    </AbsoluteFill>
  );
};
