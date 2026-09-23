import React, { useMemo } from "react";
import type { Actor, Character } from "../types";
import { isPerson } from "../types";
import { Layer } from "../kit/camera";
import { onTwos, poseAt } from "../kit/motion";
import { boil } from "../kit/paper";
import { DrawFn, PaperCanvas } from "../kit/PaperCanvas";
import { drawProp, propAspect } from "../props/library";
import { bodyOf, lookOf } from "../puppet/character";
import { drawPerson } from "../puppet/draw";
import { personPose } from "../puppet/pose";

const RAD = Math.PI / 180;

function drawActor(ctx: CanvasRenderingContext2D, a: Actor, seed: number, t: number, b: number, W: number, H: number, cast: Map<string, Character>) {
  if (isPerson(a)) {
    const ch = cast.get(a.who);
    const body = bodyOf(ch);
    const pose = personPose(a, body, t, seed);
    if (!pose.visible) return;
    const u = (a.height ?? (ch?.age === "child" ? 0.24 : 0.34)) * H;
    ctx.save();
    ctx.translate(pose.x * W + pose.jx, a.y * H + pose.dy);
    ctx.scale(pose.sx, pose.sy);
    ctx.rotate(pose.lean * RAD); // inside the mirror, so they always lean forward
    const held = a.holding ? { prop: a.holding.prop, color: a.holding.color } : undefined;
    drawPerson(ctx, lookOf(ch), body, pose, u, seed, b, held);
    ctx.restore();
    return;
  }
  const aspect = propAspect(a.prop, a.aspect);
  const pose = poseAt(a, aspect, t, W, H, seed);
  if (!pose.visible) return;
  ctx.save();
  ctx.translate(a.x * W + pose.dx, a.y * H + pose.dy);
  ctx.rotate(pose.rot * RAD);
  ctx.scale(pose.sx, pose.sy);
  drawProp(ctx, a.prop, a.height * H, seed + b * 7, { color: a.color, color2: a.color2, text: a.text, mould: a.mould, shapes: a.shapes, t: onTwos(t) }, aspect);
  ctx.restore();
}

// People and props, one canvas per depth plane, drawn in list order.
export const Actors: React.FC<{ actors: Actor[]; cast: Character[]; sceneIndex: number; lead: number; W: number; H: number }> = ({
  actors,
  cast,
  sceneIndex,
  lead,
  W,
  H,
}) => {
  const castMap = useMemo(() => new Map(cast.map((c) => [c.id, c])), [cast]);
  const planes = useMemo(() => {
    const byDepth = new Map<number, { a: Actor; i: number }[]>();
    actors.forEach((a, i) => {
      const d = a.depth ?? 1;
      if (!byDepth.has(d)) byDepth.set(d, []);
      byDepth.get(d)!.push({ a, i });
    });
    return [...byDepth.entries()].sort((x, y) => x[0] - y[0]);
  }, [actors]);

  return (
    <>
      {planes.map(([depth, list]) => (
        <Layer key={depth} depth={depth} W={W} H={H}>
          <ActorCanvas list={list} castMap={castMap} sceneIndex={sceneIndex} lead={lead} />
        </Layer>
      ))}
    </>
  );
};

const ActorCanvas: React.FC<{ list: { a: Actor; i: number }[]; castMap: Map<string, Character>; sceneIndex: number; lead: number }> = ({
  list,
  castMap,
  sceneIndex,
  lead,
}) => {
  const draw: DrawFn = useMemo(
    () => (ctx, frame, fps, W, H) => {
      const t = frame / fps - lead;
      const b = boil(frame, 3);
      for (const { a, i } of list) drawActor(ctx, a, 1000 + sceneIndex * 97 + i * 37, t, b, W, H, castMap);
    },
    [list, castMap, sceneIndex, lead],
  );
  return <PaperCanvas draw={draw} />;
};
