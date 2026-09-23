import React, { useMemo } from "react";
import { AbsoluteFill } from "remotion";
import type { Character, PropName, Story } from "../types";
import { HAND_FONT } from "../kit/fonts";
import { onTwos } from "../kit/motion";
import { boil, paper, rectPts, PAPER } from "../kit/paper";
import { DrawFn, PaperCanvas } from "../kit/PaperCanvas";
import { drawProp, PROPS } from "../props/library";
import { Grain } from "../components/Grain";

// Review sheets: every character option and every prop in one place.

export const SHEET_CAST: Character[] = [
  { id: "scientist", hair: { style: "side-part", color: "#8a7f76" }, top: { style: "labcoat" }, accessories: ["bowtie"], accent: "#2b3a8f" },
  { id: "teacher", skin: "dark", hair: { style: "braids", color: "#2a1d18" }, top: { style: "dress", color: "#e9a15b" }, accessories: ["necklace"], accent: "#f2c14e" },
  { id: "grandpa", age: "elder", skin: "brown", facialHair: "beard", top: { style: "sweater", color: "#81b29a" }, bottom: { style: "trousers", color: "#6b5a4a" }, accessories: ["glasses"] },
  { id: "kid", age: "child", skin: "tan", hair: { style: "spiky", color: "#3a2a20" }, top: { style: "tshirt", color: "#d1495b" }, bottom: { style: "shorts", color: "#4f7fbf" }, hat: { style: "cap", color: "#f2c14e" } },
  { id: "queen", skin: "light", hair: { style: "long", color: "#b5542d" }, top: { style: "robe", color: "#6d4c7d" }, hat: { style: "crown" }, accessories: ["cape"], accent: "#c8553d" },
  { id: "farmer", skin: "deep", hair: { style: "headscarf" }, top: { style: "shirt", color: "#f2cc8f" }, bottom: { style: "skirt", color: "#81b29a" }, accessories: ["apron"], accent: "#4f7fbf" },
];

export const castSheet: Story = {
  title: "Cast sheet",
  cast: SHEET_CAST,
  captions: false,
  scenes: [
    {
      duration: 8,
      backdrop: { sky: "parchment" },
      camera: { move: "still" },
      actors: [
        { who: "scientist", x: 0.2, y: 0.46, height: 0.27, holding: { prop: "petri-dish", pose: "up" }, actions: [{ do: "talk", at: 1.2, dur: 2 }, { do: "nod", at: 4 }, { do: "feel", at: 5.5, face: "surprised" }] },
        { who: "teacher", x: 0.5, y: 0.46, height: 0.27, actions: [{ do: "wave", at: 0.6 }, { do: "think", at: 2.6, dur: 2 }, { do: "cheer", at: 5.4 }] },
        { who: "grandpa", x: 0.8, y: 0.46, height: 0.25, facing: "left", actions: [{ do: "shrug", at: 1 }, { do: "shake-head", at: 3 }, { do: "point", at: 4.6, dur: 1.6 }] },
        { who: "kid", x: 0.2, y: 0.88, facing: "front", face: "grin", actions: [{ do: "hop", at: 1 }, { do: "cheer", at: 2.6 }, { do: "hop", at: 5 }] },
        { who: "queen", x: 0.5, y: 0.88, height: 0.27, face: "neutral", actions: [{ do: "talk", at: 0.8, dur: 2.4 }, { do: "turn", at: 4 }, { do: "turn", at: 6 }] },
        { who: "farmer", x: 0.8, y: 0.88, height: 0.27, facing: "left", holding: { prop: "basket", pose: "down" }, actions: [{ do: "walk", at: 1, dur: 1.6, to: 0.72 }, { do: "walk", at: 3.5, dur: 1.6, to: 0.8 }, { do: "feel", at: 5.5, face: "grin" }] },
      ],
    },
  ],
};

const NAMES = Object.keys(PROPS) as PropName[];

export const PropSheet: React.FC = () => {
  const draw: DrawFn = useMemo(
    () => (ctx, frame, fps, W, H) => {
      const t = onTwos(frame / fps);
      const b = boil(frame, 3);
      paper(ctx, rectPts(-40, -40, W + 80, H + 80), "#efe2c4", 1000 + b, { edge: 0, texture: 1, shadow: false });
      const cols = 6;
      const rows = Math.ceil(NAMES.length / cols);
      const cw = W / cols, rh = (H - 80) / rows;
      NAMES.forEach((name, i) => {
        const cx = (i % cols) * cw + cw / 2;
        const cy = 60 + Math.floor(i / cols) * rh;
        const def = PROPS[name];
        const s = Math.min(rh * 0.62, (cw * 0.78) / def.aspect);
        ctx.save();
        ctx.translate(cx, cy + rh * 0.72);
        if (name === "shapes") {
          drawProp(ctx, name, s, 50 + i * 13 + b * 7, {
            t,
            shapes: [
              { type: "rect", x: 0.3, y: 0.3, w: 0.4, h: 0.7, color: "#f6efdc" },
              { type: "poly", points: [[0.22, 0.32], [0.5, 0.0], [0.78, 0.32]], color: "#d1495b" },
              { type: "rect", x: 0.3, y: 0.55, w: 0.4, h: 0.1, color: "#d1495b" },
            ],
          });
        } else {
          drawProp(ctx, name, s, 50 + i * 13 + b * 7, { t, text: name === "sign" ? "Hello" : name === "book" ? "Facts" : undefined, mould: name === "petri-dish" });
        }
        ctx.restore();
        ctx.font = `34px ${HAND_FONT}`;
        ctx.fillStyle = "#3b2f2a";
        ctx.textAlign = "center";
        ctx.fillText(name, cx, cy + rh * 0.9);
      });
      paper(ctx, rectPts(W / 2 - 170, 8, 340, 50), PAPER, 77 + b, { edge: 0, rough: 4, texture: 0.3 });
      ctx.font = `38px ${HAND_FONT}`;
      ctx.fillStyle = "#2b3a8f";
      ctx.fillText("prop library", W / 2, 44);
    },
    [],
  );
  return (
    <AbsoluteFill>
      <PaperCanvas draw={draw} overscan={0} />
      <Grain />
    </AbsoluteFill>
  );
};
