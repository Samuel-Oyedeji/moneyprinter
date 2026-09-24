import { capsulePts, roundRectPts } from "../kit/pen";
import { ellipsePts, paper, paperGroup, PaperOpts, Pt, rectPts, shade } from "../kit/paper";
import { drawProp, PROPS } from "../props/library";
import type { PropName } from "../types";
import type { Body, Look } from "./character";
import type { Limb, PuppetPose } from "./pose";

// Draws one paper person with the feet at the canvas origin, facing right
// (the caller mirrors for facing left). Every body part is its own torn
// piece of paper, pinned at the joints like a paper puppet.

const INK = "#2b2230";
const BLUSH = "#f29a9a";
const RAD = Math.PI / 180;

// stable per-part seed so a part keeps its own torn edge between boils
function hash(s: string) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return (h >>> 0) % 100000;
}

type Held = { prop: PropName; color?: string; size?: number } | undefined;

export function drawPerson(ctx: CanvasRenderingContext2D, look: Look, B: Body, pose: PuppetPose, u: number, seed: number, boilSeed: number, held: Held) {
  const o: PaperOpts = {
    edge: Math.min(5, Math.max(2, u * 0.008)),
    rough: Math.min(3, Math.max(1, u * 0.005)),
    texture: 0.45,
    brush: Math.min(0.6, Math.max(0.22, u / 1100)),
    lift: Math.min(0.8, Math.max(0.35, u / 900)),
  };
  const P = (x: number, y: number): Pt => [x * u, y * u];
  const part = (name: string, pts: Pt[], color: string, extra: PaperOpts = {}) =>
    paper(ctx, pts, color, seed + hash(name) + boilSeed * 7, { ...o, ...extra });
  const group = (name: string, shapes: Pt[][], color: string, extra: PaperOpts = {}) =>
    paperGroup(ctx, shapes, color, seed + hash(name) + boilSeed * 7, { ...o, ...extra });
  const scaled = (pts: Pt[]) => pts.map(([x, y]) => P(x, y));
  const ell = (cx: number, cy: number, rx: number, ry: number, n = 32) => scaled(ellipsePts(cx, cy, rx, ry, n));
  const flat = { shadow: false, edge: 0, texture: 0 } as PaperOpts;

  const f = pose.front ? 0 : 1; // 1 = three-quarter view facing right
  const top = look.top.style;
  const longSleeves = !(top === "tshirt" || top === "dress");
  const r = B.headR;
  const hcy = B.headCY;
  const hairOf = look.hair.style;

  // limb endpoints
  const limb = (sx: number, sy: number, L: Limb, l1: number, l2: number) => {
    const ex = sx + Math.sin(L.up * RAD) * l1, ey = sy + Math.cos(L.up * RAD) * l1;
    const hx = ex + Math.sin(L.lo * RAD) * l2, hy = ey + Math.cos(L.lo * RAD) * l2;
    return { ex, ey, hx, hy };
  };
  const shY = B.shoulderY + 0.02;
  const shX = B.sh * 0.92;
  const armF = limb(shX, shY, pose.armF, B.armUp, B.armLo);
  const armB = limb(-shX, shY, pose.armB, B.armUp, B.armLo);
  const legF = limb(B.legX, B.hipY, pose.legF, B.legUp, B.legLo);
  const legB = limb(-B.legX, B.hipY, pose.legB, B.legUp, B.legLo);

  // head transform (nods, tilts, head shakes) pivots on the neck
  const neckY = B.shoulderY - 0.01;
  const withHead = (fn: () => void) => {
    ctx.save();
    ctx.translate(pose.headDx * u, neckY * u);
    ctx.rotate(pose.headTilt * RAD);
    ctx.translate(0, -neckY * u);
    fn();
    ctx.restore();
  };

  // ---------------------------------------------------------------- back
  if (look.acc.has("cape")) {
    part("cape", scaled([[-B.sh, B.shoulderY], [B.sh, B.shoulderY], [B.sh * 1.6, -0.05], [-B.sh * 1.6, -0.05]]), look.accent);
  }
  if (look.kind === "astronaut") {
    part("pack", roundRectPts((-B.sh * 1.08 - f * 0.05) * u, (B.shoulderY - 0.02) * u, B.sh * 2.16 * u, 0.3 * u, 0.04 * u), "#c9cfd6");
  }
  if (look.kind === "animal") drawTail();
  withHead(() => hairBack());

  // ---------------------------------------------------------------- legs
  const legColor = look.bottom.style === "trousers" && top !== "robe" && top !== "dress" ? look.bottom.color : look.skin;
  for (const [name, L, hipX] of [["legB", legB, -B.legX], ["legF", legF, B.legX]] as const) {
    part(`${name}-thigh`, capsulePts(hipX * u, B.hipY * u, L.ex * u, L.ey * u, B.legW * u), legColor, { angle: Math.PI / 2 });
    part(`${name}-shin`, capsulePts(L.ex * u, L.ey * u, L.hx * u, L.hy * u, B.legW * 0.92 * u), legColor, { angle: Math.PI / 2 });
    if (look.kind === "robot") part(`${name}-knee`, ell(L.ex, L.ey, B.legW * 0.62, B.legW * 0.62, 14), shade(legColor, -0.12));
    if (look.bottom.style === "shorts" && top !== "robe" && top !== "dress") {
      const mx = hipX + (L.ex - hipX) * 0.55, my = B.hipY + (L.ey - B.hipY) * 0.55;
      part(`${name}-shorts`, capsulePts(hipX * u, B.hipY * u, mx * u, my * u, B.legW * 1.15 * u), look.bottom.color);
    }
    const shoeX = L.hx + f * B.shoeL * 0.32;
    const boot = look.kind === "astronaut" ? 1.3 : look.kind === "robot" ? 1.15 : 1;
    part(`${name}-shoe`, ell(shoeX, L.hy + B.shoeH * 0.35, B.shoeL * (f ? 0.55 : 0.42) * boot, B.shoeH * boot), look.shoes);
  }

  // ---------------------------------------------------------------- hips & skirts
  const hh = B.hh;
  if (top === "robe") {
    part("robe-skirt", scaled([[-hh, B.hipY - 0.04], [hh, B.hipY - 0.04], [hh * 1.4, -0.045], [-hh * 1.4, -0.045]]), look.top.color, { angle: Math.PI / 2 });
  } else if (top === "dress") {
    part("dress-skirt", scaled([[-hh, B.hipY - 0.04], [hh, B.hipY - 0.04], [hh * 1.55, B.hipY + 0.2], [-hh * 1.55, B.hipY + 0.2]]), look.top.color);
  } else if (look.bottom.style === "kilt") {
    const kx = f * 0.012;
    part("kilt", scaled([[-hh, B.hipY - 0.04], [hh, B.hipY - 0.04], [hh * 1.35, B.hipY + 0.14], [-hh * 1.35, B.hipY + 0.14]]), look.bottom.color);
    part("kilt-front", scaled([[kx - 0.035, B.hipY - 0.02], [kx + 0.035, B.hipY - 0.02], [kx + 0.06, B.hipY + 0.14], [kx - 0.06, B.hipY + 0.14]]), "#e8b54a");
    part("kilt-belt", rectPts(-hh * 1.05 * u, (B.hipY - 0.05) * u, hh * 2.1 * u, 0.03 * u), "#e8b54a");
  } else if (look.bottom.style === "skirt") {
    part("skirt", scaled([[-hh, B.hipY - 0.04], [hh, B.hipY - 0.04], [hh * 1.5, B.hipY + 0.18], [-hh * 1.5, B.hipY + 0.18]]), look.bottom.color);
  } else {
    part("hips", roundRectPts(-hh * u, (B.hipY - 0.04) * u, hh * 2 * u, 0.1 * u, 0.03 * u), look.bottom.color);
  }
  if (top === "labcoat" || top === "coat") {
    const hem = B.hipY + 0.2;
    part("coat-back", scaled([[-hh * 1.05, B.hipY - 0.04], [-0.012, B.hipY - 0.04], [-0.02, hem], [-hh * 1.32, hem]]), look.top.color);
    part("coat-front", scaled([[0.012, B.hipY - 0.04], [hh * 1.05, B.hipY - 0.04], [hh * 1.32, hem], [0.02, hem]]), look.top.color);
  }

  // ---------------------------------------------------------------- torso
  part("neck", rectPts((-B.neckW / 2) * u, (B.shoulderY - 0.05) * u, B.neckW * u, 0.08 * u), shade(look.skin, -0.06));
  const sh = B.sh;
  const sy = B.shoulderY;
  const hem = top === "suit" ? B.hipY + 0.04 : B.hipY + 0.01;
  const rc = 0.05;
  const torso: Pt[] = [];
  for (let i = 0; i <= 6; i++) {
    const a = Math.PI + (i / 6) * (Math.PI / 2);
    torso.push([-sh + rc + Math.cos(a) * rc, sy + rc + Math.sin(a) * rc]);
  }
  for (let i = 0; i <= 6; i++) {
    const a = -Math.PI / 2 + (i / 6) * (Math.PI / 2);
    torso.push([sh - rc + Math.cos(a) * rc, sy + rc + Math.sin(a) * rc]);
  }
  torso.push([hh * 1.04, hem], [-hh * 1.04, hem]);
  part("torso", scaled(torso), look.top.color, { angle: Math.PI / 2 });

  const inner = look.top.inner;
  const cx = f * 0.012; // front seam shifts a little toward the way they face
  if (top === "suit" || top === "labcoat" || top === "coat") {
    // the shirt/vest showing in the opening, then lapels
    const vDepth = top === "suit" ? 0.14 : hem - sy - 0.02;
    part("opening", scaled([[cx - 0.06, sy - 0.005], [cx + 0.06, sy - 0.005], [cx + (top === "suit" ? 0 : 0.035), sy + vDepth], [cx - (top === "suit" ? 0 : 0.035), sy + vDepth]]), inner);
    if (top !== "suit") {
      part("shirt-v", scaled([[cx - 0.045, sy - 0.005], [cx + 0.045, sy - 0.005], [cx, sy + 0.1]]), "#f4f1ea", { shadow: false });
      for (let i = 0; i < 3; i++) part(`vest-btn-${i}`, ell(cx, sy + 0.15 + i * 0.05, 0.007, 0.007, 10), shade(inner, -0.15), flat);
    }
    const lap = top === "labcoat" ? shade(look.top.color, -0.07) : shade(look.top.color, -0.1);
    part("lapel-l", scaled([[cx - 0.065, sy - 0.005], [cx - 0.012, sy + 0.14], [cx - 0.085, sy + 0.07]]), lap);
    part("lapel-r", scaled([[cx + 0.065, sy - 0.005], [cx + 0.012, sy + 0.14], [cx + 0.085, sy + 0.07]]), lap);
    if (top === "suit") for (let i = 0; i < 2; i++) part(`btn-${i}`, ell(cx + 0.01, sy + 0.2 + i * 0.06, 0.008, 0.008, 10), shade(look.top.color, -0.25), flat);
    if (top === "labcoat") part("pocket", roundRectPts((cx + 0.04) * u, (sy + 0.1) * u, 0.06 * u, 0.05 * u, 0.008 * u), shade(look.top.color, -0.04));
  } else if (top === "shirt") {
    part("collar-l", scaled([[cx - 0.055, sy - 0.01], [cx, sy + 0.035], [cx - 0.05, sy + 0.05]]), shade(look.top.color, 0.08));
    part("collar-r", scaled([[cx + 0.055, sy - 0.01], [cx, sy + 0.035], [cx + 0.05, sy + 0.05]]), shade(look.top.color, 0.08));
    for (let i = 0; i < 3; i++) part(`sbtn-${i}`, ell(cx, sy + 0.08 + i * 0.07, 0.007, 0.007, 10), shade(look.top.color, -0.2), flat);
  } else if (top === "sweater") {
    part("neckband", ell(cx, sy + 0.005, 0.06, 0.025), shade(look.top.color, -0.1));
    part("hemband", rectPts(-hh * 1.04 * u, (hem - 0.035) * u, hh * 2.08 * u, 0.035 * u), shade(look.top.color, -0.1), { shadow: false });
  } else if (top === "spacesuit") {
    part("suit-collar", ell(cx, sy - 0.005, 0.1, 0.03), "#c9cfd6");
    part("chest-panel", roundRectPts((cx - 0.06) * u, (sy + 0.07) * u, 0.12 * u, 0.08 * u, 0.01 * u), "#c9cfd6");
    ["#d1495b", "#4f7fbf", "#f2c14e"].forEach((c, i) => part(`suit-btn-${i}`, ell(cx - 0.035 + i * 0.035, sy + 0.11, 0.011, 0.011, 10), c, flat));
    part("suit-waist", rectPts(-hh * 1.05 * u, (B.hipY - 0.045) * u, hh * 2.1 * u, 0.035 * u), "#c9cfd6");
  } else if (top === "armor") {
    for (let i = 0; i < 2; i++) part(`plate-${i}`, rectPts(-hh * 1.02 * u, (sy + 0.1 + i * 0.09) * u, hh * 2.04 * u, 0.012 * u), shade(look.top.color, -0.14), { shadow: false });
    part("tabard", scaled([[cx - hh * 0.62, sy + 0.02], [cx + hh * 0.62, sy + 0.02], [cx + hh * 0.7, B.hipY + 0.12], [cx - hh * 0.7, B.hipY + 0.12]]), inner);
    part("emblem", ell(cx, sy + 0.14, 0.035, 0.035, 16), "#f2c14e");
    part("armor-belt", rectPts(-hh * 1.05 * u, (B.hipY - 0.035) * u, hh * 2.1 * u, 0.03 * u), "#5a4636");
  } else if (top === "robot") {
    part("robot-panel", roundRectPts((cx - 0.065) * u, (sy + 0.06) * u, 0.13 * u, 0.1 * u, 0.012 * u), "#26303a");
    part("robot-light", ell(cx - 0.03, sy + 0.1, 0.014, 0.014, 12), look.top.inner, flat);
    part("robot-light2", ell(cx + 0.02, sy + 0.1, 0.014, 0.014, 12), "#7fe3f0", flat);
    for (const [rx, ry] of [[-hh * 0.8, sy + 0.04], [hh * 0.8, sy + 0.04], [-hh * 0.8, B.hipY - 0.02], [hh * 0.8, B.hipY - 0.02]]) {
      part(`rivet-${rx}-${ry}`, ell(rx, ry, 0.008, 0.008, 8), shade(look.top.color, -0.2), flat);
    }
  } else if (top === "bare") {
    // skin: the broad collar dresses it
  } else if (top === "robe") {
    part("robe-fold", scaled([[cx - 0.05, sy], [cx + 0.07, sy], [cx - 0.02, hem - 0.02], [cx - 0.08, hem - 0.02]]), shade(look.top.color, -0.1));
    part("sash", rectPts(-hh * 1.05 * u, (B.hipY - 0.05) * u, hh * 2.1 * u, 0.035 * u), look.accent);
  } else {
    part("neckline", ell(cx, sy + 0.005, 0.055, 0.03), shade(look.top.color, -0.12));
  }

  if (look.acc.has("apron")) part("apron", roundRectPts(-hh * 0.85 * u, (sy + 0.1) * u, hh * 1.7 * u, (B.hipY + 0.17 - sy - 0.1) * u, 0.02 * u), "#f4f1ea");
  if (look.acc.has("belt")) {
    part("belt", rectPts(-hh * 1.05 * u, (B.hipY - 0.03) * u, hh * 2.1 * u, 0.028 * u), "#3b2f2a");
    part("buckle", rectPts((cx - 0.018) * u, (B.hipY - 0.034) * u, 0.036 * u, 0.036 * u), "#f2c14e", { shadow: false });
  }
  if (look.acc.has("necklace")) for (let i = 0; i < 7; i++) {
    const a = Math.PI * (0.2 + (i / 6) * 0.6);
    part(`bead-${i}`, ell(cx + Math.cos(a) * 0.06, sy + Math.sin(a) * 0.06, 0.009, 0.009, 10), look.accent, { edge: 0 });
  }
  if (look.acc.has("collar")) {
    // an Egyptian broad collar: bands of gold, turquoise and red
    const bands = ["#3fa7a0", "#e8b54a", "#c8553d", "#e8b54a"];
    bands.forEach((c, k) => {
      const R = 0.135 - k * 0.022;
      const pts: Pt[] = [];
      for (let i = 0; i <= 16; i++) {
        const a = (i / 16) * Math.PI;
        pts.push([cx + Math.cos(a) * R * 1.25, sy - 0.012 + Math.sin(a) * R]);
      }
      part(`collar-${k}`, scaled(pts), c, k ? { shadow: false } : {});
    });
    const neck: Pt[] = [];
    for (let i = 0; i <= 12; i++) neck.push([cx + Math.cos((i / 12) * Math.PI) * 0.05, sy - 0.012 + Math.sin((i / 12) * Math.PI) * 0.035]);
    part("collar-neck", scaled(neck), look.skin, { shadow: false, edge: 0 });
  }
  if (look.acc.has("tie")) {
    part("tie", scaled([[cx - 0.014, sy + 0.012], [cx + 0.014, sy + 0.012], [cx + 0.024, sy + 0.2], [cx, sy + 0.23], [cx - 0.024, sy + 0.2]]), look.accent);
  }
  if (look.acc.has("bowtie")) {
    group("bowtie", [
      scaled([[cx, sy + 0.018], [cx - 0.045, sy - 0.004], [cx - 0.045, sy + 0.04]]),
      scaled([[cx, sy + 0.018], [cx + 0.045, sy - 0.004], [cx + 0.045, sy + 0.04]]),
      ell(cx, sy + 0.018, 0.012, 0.012, 10),
    ], look.accent);
  }
  if (look.acc.has("scarf")) {
    part("scarf", roundRectPts((-B.neckW * 0.95) * u, (sy - 0.03) * u, B.neckW * 1.9 * u, 0.05 * u, 0.02 * u), look.accent);
    part("scarf-tail", scaled([[cx + 0.02, sy + 0.01], [cx + 0.055, sy + 0.01], [cx + 0.07, sy + 0.16], [cx + 0.035, sy + 0.16]]), shade(look.accent, -0.06));
  }

  // ---------------------------------------------------------------- head
  withHead(() => {
    if (look.kind === "robot") return robotHead();
    if (look.kind === "animal") {
      animalHead();
      drawHat();
      if (look.acc.has("glasses")) glasses();
      return;
    }
    const ears = !["long", "bob", "afro", "headscarf", "braids"].includes(hairOf) && look.hat?.style !== "nemes";
    if (ears) {
      if (f) part("ear", ell(-0.62 * r, hcy + 0.05 * r, 0.2 * r, 0.24 * r, 16), look.skin);
      else for (const s of [-1, 1]) part(`ear-${s}`, ell(s * 0.98 * r, hcy + 0.06 * r, 0.18 * r, 0.22 * r, 16), look.skin);
    }
    part("head", ell(0, hcy, r, r * 1.03, 40), look.skin, { texture: 0.4 });
    drawFace();
    hairFront();
    drawHat();
    if (look.acc.has("glasses")) glasses();
  });

  // ---------------------------------------------------------------- arms
  const sleeve = look.top.color;
  const drawArm = (name: string, sx: number, A: { ex: number; ey: number; hx: number; hy: number }) => {
    const upColor = sleeve;
    part(`${name}-upper`, capsulePts(sx * u, shY * u, A.ex * u, A.ey * u, B.armW * u), upColor, { angle: Math.PI / 2 });
    if (look.kind === "robot") part(`${name}-elbow`, ell(A.ex, A.ey, B.armW * 0.66, B.armW * 0.66, 14), shade(sleeve, -0.12));
    part(`${name}-fore`, capsulePts(A.ex * u, A.ey * u, A.hx * u, A.hy * u, B.armW * 0.9 * u), longSleeves ? sleeve : look.skin, { angle: Math.PI / 2 });
    if (top === "suit") {
      const kx = A.ex + (A.hx - A.ex) * 0.86, ky = A.ey + (A.hy - A.ey) * 0.86;
      part(`${name}-cuff`, capsulePts(kx * u, ky * u, A.hx * u, A.hy * u, B.armW * 0.85 * u), "#f4f1ea", { shadow: false });
    }
    if (look.kind === "pharaoh") {
      const bx = sx + (A.ex - sx) * 0.45, by = shY + (A.ey - shY) * 0.45;
      part(`${name}-armband`, capsulePts(bx * u, by * u, (sx + (A.ex - sx) * 0.58) * u, (shY + (A.ey - shY) * 0.58) * u, B.armW * 1.1 * u), "#e8b54a", { shadow: false });
      part(`${name}-bracelet`, capsulePts((A.ex + (A.hx - A.ex) * 0.78) * u, (A.ey + (A.hy - A.ey) * 0.78) * u, (A.ex + (A.hx - A.ex) * 0.9) * u, (A.ey + (A.hy - A.ey) * 0.9) * u, B.armW * 1.0 * u), "#e8b54a", { shadow: false });
    }
    const hr = B.handR * (look.kind === "astronaut" ? 1.3 : look.kind === "knight" ? 1.12 : 1);
    part(`${name}-hand`, ell(A.hx, A.hy, hr, hr, 16), look.hands);
    if (top === "armor") part(`${name}-pauldron`, ell(sx + (A.ex - sx) * 0.1, shY + (A.ey - shY) * 0.1, B.armW * 0.95, B.armW * 0.8, 18), shade(sleeve, 0.06));
  };
  drawArm("armB", -shX, armB);
  if (held) {
    const def = PROPS[held.prop];
    const ph = (held.size ?? def.held) * u;
    ctx.save();
    if (pose.holdUp) ctx.translate(armF.hx * u, (armF.hy - B.handR * 0.4) * u);
    else ctx.translate(armF.hx * u, armF.hy * u + ph - B.handR * 0.4 * u);
    drawProp(ctx, held.prop, ph, seed + 555 + boilSeed * 7, { color: held.color, t: 0 });
    ctx.restore();
  }
  drawArm("armF", shX, armF);

  // ================================================================ face parts
  function drawFace() {
    const fx = f * 0.2 * r;
    const ey = hcy + 0.02 * r;
    const eyes = [fx - 0.32 * r, fx + 0.32 * r];
    // cheeks
    ctx.globalAlpha = 0.5;
    for (const ex of eyes) part(`cheek-${ex > fx}`, ell(ex + (ex > fx ? 0.16 : -0.16) * r, hcy + 0.27 * r, 0.12 * r, 0.075 * r, 16), BLUSH, flat);
    ctx.globalAlpha = 1;
    // nose
    part("nose", ell(fx + f * 0.06 * r, hcy + 0.18 * r, 0.075 * r, 0.06 * r, 12), shade(look.skin, -0.07), flat);
    eyesAndBrows(fx, ey, eyes);
    // facial hair sits under the mouth
    if (look.facialHair === "beard") {
      const pts: Pt[] = [];
      for (let i = 0; i <= 16; i++) {
        const a = (10 + (i / 16) * 160) * RAD;
        pts.push([Math.cos(a) * r * 1.03, hcy + Math.sin(a) * r * 1.06]);
      }
      pts.push([-0.7 * r, hcy + 0.3 * r], [fx, hcy + 0.36 * r], [0.7 * r, hcy + 0.3 * r]);
      part("beard", scaled(pts), look.hair.color);
    }
    if (look.facialHair === "goatee") part("goatee", ell(fx + 0.03 * r, hcy + 0.62 * r, 0.14 * r, 0.12 * r, 16), look.hair.color);
    mouth(fx + f * 0.03 * r, hcy + 0.44 * r);
    if (look.facialHair === "mustache" || look.facialHair === "beard") {
      group("mustache", [ell(fx - 0.07 * r, hcy + 0.33 * r, 0.12 * r, 0.05 * r, 16), ell(fx + 0.11 * r, hcy + 0.33 * r, 0.12 * r, 0.05 * r, 16)], look.hair.color, { shadow: false });
    }
    if (look.kind === "pharaoh") {
      // the ceremonial beard
      part("royal-beard", roundRectPts((fx - 0.08 * r) * u, (hcy + 0.82 * r) * u, 0.16 * r * u, 0.44 * r * u, 0.05 * r * u), "#2f5d9a");
      for (let k = 0; k < 2; k++) part(`royal-beard-${k}`, rectPts((fx - 0.08 * r) * u, (hcy + (0.95 + k * 0.14) * r) * u, 0.16 * r * u, 0.05 * r * u), "#e8b54a", flat);
    }
  }

  function eyesAndBrows(fx: number, ey: number, eyes: number[]) {
    const lx = pose.lookX * 0.07 * r, ly = pose.lookY * 0.06 * r;
    ctx.fillStyle = INK;
    ctx.strokeStyle = INK;
    ctx.lineCap = "round";
    ctx.lineWidth = 0.045 * r * u;
    for (const ex of eyes) {
      const X = (ex + lx) * u, Y = (ey + ly) * u;
      const rx = 0.1 * r * u, ry = 0.125 * r * u;
      ctx.beginPath();
      if (pose.eyes === "closed" || pose.eyes === "happy") {
        const up = pose.eyes === "happy" ? -1 : 1;
        ctx.arc(X, Y + (up > 0 ? -0.02 : 0.05) * r * u, rx * 1.1, up > 0 ? 0.15 * Math.PI : 1.15 * Math.PI, up > 0 ? 0.85 * Math.PI : 1.85 * Math.PI);
        ctx.stroke();
        continue;
      }
      const k = pose.eyes === "wide" ? 1.3 : 1;
      if (pose.eyes === "sleepy") {
        ctx.ellipse(X, Y, rx, ry, 0, 0, Math.PI);
        ctx.fill();
        continue;
      }
      ctx.ellipse(X, Y, rx * k, ry * k, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.beginPath();
      ctx.arc(X + rx * 0.35, Y - ry * 0.35, rx * 0.36, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = INK;
      if (look.kind === "pharaoh") {
        // kohl: a line out from the outer corner
        const out = ex > fx ? 1 : -1;
        ctx.beginPath();
        ctx.moveTo(X + out * rx, Y);
        ctx.lineTo(X + out * rx * 2.4, Y - 0.03 * r * u);
        ctx.stroke();
      }
    }
    // brows
    const browColor = hairOf === "bald" || hairOf === "balding" ? shade(look.skin, -0.3) : shade(look.hair.color, -0.1);
    ctx.strokeStyle = browColor;
    ctx.lineWidth = 0.05 * r * u;
    const by = ey - (pose.brows === "raised" ? 0.32 : 0.24) * r;
    for (const ex of eyes) {
      const inner = ex > fx ? -1 : 1; // direction toward the nose
      const tilt = pose.brows === "worried" ? -0.06 : pose.brows === "angry" ? 0.07 : 0;
      ctx.beginPath();
      ctx.moveTo((ex - inner * 0.1 * r) * u, by * u);
      ctx.lineTo((ex + inner * 0.1 * r) * u, (by + tilt * r) * u);
      ctx.stroke();
    }
  }

  function mouth(mx: number, my: number) {
    const X = mx * u, Y = my * u, R = r * u;
    ctx.strokeStyle = INK;
    ctx.fillStyle = "#6e2a2a";
    ctx.lineWidth = 0.05 * R;
    ctx.lineCap = "round";
    ctx.beginPath();
    switch (pose.mouth) {
      case "smile":
        ctx.arc(X, Y - 0.12 * R, 0.16 * R, 0.18 * Math.PI, 0.82 * Math.PI);
        ctx.stroke();
        break;
      case "grin":
        ctx.moveTo(X - 0.19 * R, Y - 0.05 * R);
        ctx.lineTo(X + 0.19 * R, Y - 0.05 * R);
        ctx.ellipse(X, Y - 0.05 * R, 0.19 * R, 0.17 * R, 0, 0, Math.PI);
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.fillRect(X - 0.13 * R, Y - 0.05 * R, 0.26 * R, 0.05 * R);
        break;
      case "neutral":
        ctx.moveTo(X - 0.1 * R, Y);
        ctx.lineTo(X + 0.1 * R, Y);
        ctx.stroke();
        break;
      case "frown":
        ctx.arc(X, Y + 0.14 * R, 0.14 * R, 1.2 * Math.PI, 1.8 * Math.PI);
        ctx.stroke();
        break;
      case "wavy":
        ctx.moveTo(X - 0.12 * R, Y);
        ctx.quadraticCurveTo(X - 0.06 * R, Y - 0.05 * R, X, Y);
        ctx.quadraticCurveTo(X + 0.06 * R, Y + 0.05 * R, X + 0.12 * R, Y);
        ctx.stroke();
        break;
      case "o":
        ctx.ellipse(X, Y, 0.07 * R, 0.09 * R, 0, 0, Math.PI * 2);
        ctx.fill();
        break;
      case "talk1":
        ctx.ellipse(X, Y - 0.02 * R, 0.1 * R, 0.055 * R, 0, 0, Math.PI * 2);
        ctx.fill();
        break;
      case "talk2":
        ctx.ellipse(X, Y, 0.12 * R, 0.1 * R, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#d9737a";
        ctx.beginPath();
        ctx.ellipse(X, Y + 0.05 * R, 0.07 * R, 0.035 * R, 0, 0, Math.PI * 2);
        ctx.fill();
        break;
    }
  }

  function glasses() {
    const fx = f * 0.2 * r;
    ctx.strokeStyle = INK;
    ctx.lineWidth = 0.035 * r * u;
    for (const ex of [fx - 0.32 * r, fx + 0.32 * r]) {
      ctx.fillStyle = "rgba(255,255,255,0.22)";
      ctx.beginPath();
      ctx.arc(ex * u, (hcy + 0.02 * r) * u, 0.19 * r * u, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.moveTo((fx - 0.13 * r) * u, (hcy - 0.01 * r) * u);
    ctx.lineTo((fx + 0.13 * r) * u, (hcy - 0.01 * r) * u);
    ctx.stroke();
  }

  // ================================================================ robots
  function robotHead() {
    const fx = f * 0.15 * r;
    const metal = look.skin;
    part("antenna", capsulePts(0, (hcy - 0.85 * r) * u, 0, (hcy - 1.42 * r) * u, 0.08 * r * u), shade(metal, -0.15));
    part("antenna-ball", ell(0, hcy - 1.48 * r, 0.15 * r, 0.15 * r, 14), look.accent);
    if (f) part("bolt", ell(-0.98 * r, hcy, 0.2 * r, 0.28 * r, 16), shade(metal, -0.12));
    else for (const side of [-1, 1]) part(`bolt-${side}`, ell(side * 1.08 * r, hcy, 0.18 * r, 0.26 * r, 16), shade(metal, -0.12));
    part("robot-head", roundRectPts(-1.05 * r * u, (hcy - 0.9 * r) * u, 2.1 * r * u, 1.8 * r * u, 0.3 * r * u), metal, { texture: 0.4 });
    part("screen", roundRectPts((fx - 0.72 * r) * u, (hcy - 0.58 * r) * u, 1.44 * r * u, 1.12 * r * u, 0.18 * r * u), "#26303a", { shadow: false });
    // LED eyes, brows and mouth: every expression still reads
    const led = "#7fe3f0";
    const lx = pose.lookX * 0.06 * r, ly = pose.lookY * 0.05 * r;
    ctx.save();
    ctx.fillStyle = led;
    ctx.strokeStyle = led;
    ctx.lineCap = "round";
    ctx.lineWidth = 0.09 * r * u;
    ctx.shadowColor = led;
    ctx.shadowBlur = 0.3 * r * u;
    for (const ex of [fx - 0.3 * r, fx + 0.3 * r]) {
      const X = (ex + lx) * u, Y = (hcy - 0.12 * r + ly) * u, R = 0.14 * r * u;
      ctx.beginPath();
      if (pose.eyes === "closed" || pose.eyes === "happy") {
        const up = pose.eyes === "happy";
        ctx.arc(X, Y + (up ? 0.06 : -0.04) * r * u, R, up ? 1.15 * Math.PI : 0.15 * Math.PI, up ? 1.85 * Math.PI : 0.85 * Math.PI);
        ctx.stroke();
      } else if (pose.eyes === "sleepy") {
        ctx.fillRect(X - R, Y - R * 0.2, R * 2, R * 0.5);
      } else {
        ctx.arc(X, Y, R * (pose.eyes === "wide" ? 1.3 : 1), 0, Math.PI * 2);
        ctx.fill();
      }
      if (pose.brows === "angry" || pose.brows === "worried" || pose.brows === "raised") {
        const inner = ex > fx ? -1 : 1;
        const tilt = pose.brows === "angry" ? 0.1 : pose.brows === "worried" ? -0.1 : 0;
        const by = hcy - (pose.brows === "raised" ? 0.44 : 0.36) * r;
        ctx.beginPath();
        ctx.moveTo((ex - inner * 0.14 * r) * u, by * u);
        ctx.lineTo((ex + inner * 0.14 * r) * u, (by + tilt * r) * u);
        ctx.stroke();
      }
    }
    const MX = fx * u, MY = (hcy + 0.27 * r) * u, W = 0.26 * r * u;
    ctx.beginPath();
    switch (pose.mouth) {
      case "smile":
        ctx.arc(MX, MY - W * 0.6, W, 0.2 * Math.PI, 0.8 * Math.PI);
        ctx.stroke();
        break;
      case "grin":
        ctx.fillRect(MX - W * 1.1, MY - W * 0.25, W * 2.2, W * 0.5);
        break;
      case "frown":
        ctx.arc(MX, MY + W * 0.8, W * 0.9, 1.2 * Math.PI, 1.8 * Math.PI);
        ctx.stroke();
        break;
      case "o":
        ctx.arc(MX, MY, W * 0.35, 0, Math.PI * 2);
        ctx.stroke();
        break;
      case "wavy":
        ctx.moveTo(MX - W, MY);
        for (let i = 1; i <= 4; i++) ctx.lineTo(MX - W + (i * W) / 2, MY + (i % 2 ? -1 : 1) * W * 0.18);
        ctx.stroke();
        break;
      case "talk1":
        ctx.fillRect(MX - W * 0.6, MY - W * 0.15, W * 1.2, W * 0.3);
        break;
      case "talk2":
        ctx.fillRect(MX - W * 0.7, MY - W * 0.3, W * 1.4, W * 0.6);
        break;
      default:
        ctx.moveTo(MX - W * 0.8, MY);
        ctx.lineTo(MX + W * 0.8, MY);
        ctx.stroke();
    }
    ctx.restore();
  }

  // ================================================================ animals
  function animalHead() {
    const sp = look.species;
    const fur = look.skin;
    const fx = f * 0.2 * r;
    const earX = (side: number, spread: number) => side * spread * r - f * 0.14 * r;
    // ears behind the head
    for (const side of [-1, 1]) {
      const x0 = earX(side, sp === "rabbit" ? 0.36 : sp === "bear" ? 0.74 : 0.56);
      if (sp === "rabbit") {
        part(`ear-${side}`, ell(x0, hcy - 1.3 * r, 0.22 * r, 0.7 * r, 24), fur);
        part(`ear-in-${side}`, ell(x0, hcy - 1.26 * r, 0.11 * r, 0.5 * r, 20), look.earInner, { shadow: false });
      } else if (sp === "bear") {
        part(`ear-${side}`, ell(x0, hcy - 0.72 * r, 0.32 * r, 0.32 * r, 20), fur);
        part(`ear-in-${side}`, ell(x0, hcy - 0.74 * r, 0.17 * r, 0.17 * r, 16), look.earInner, { shadow: false });
      } else {
        const tall = sp === "fox" ? 1.5 : 1.28;
        part(`ear-${side}`, scaled([[x0 - 0.3 * r, hcy - 0.62 * r], [x0 + 0.3 * r, hcy - 0.68 * r], [x0 + side * 0.06 * r, hcy - tall * r]]), fur);
        part(`ear-in-${side}`, scaled([[x0 - 0.15 * r, hcy - 0.7 * r], [x0 + 0.15 * r, hcy - 0.73 * r], [x0 + side * 0.04 * r, hcy - (tall - 0.22) * r]]), look.earInner, { shadow: false });
      }
    }
    part("head", ell(0, hcy, r * 1.04, r, 40), fur, { texture: 0.5 });
    if (sp === "fox" || sp === "cat") {
      // pale cheeks and chin
      part("cheeks", ell(fx + f * 0.05 * r, hcy + 0.4 * r, 0.66 * r, 0.42 * r, 28), look.muzzle, { shadow: false });
    }
    const snout = sp === "fox" ? 0.3 : sp === "bear" ? 0.18 : 0.1;
    const mx = fx + f * snout * r;
    const my = hcy + 0.3 * r;
    part("muzzle", ell(mx, my, (sp === "fox" ? 0.46 : sp === "bear" ? 0.4 : 0.34) * r, (sp === "bear" ? 0.3 : 0.26) * r, 24), look.muzzle);
    ctx.globalAlpha = 0.45;
    for (const side of [-1, 1]) part(`cheek-${side}`, ell(fx + side * 0.5 * r, hcy + 0.18 * r, 0.12 * r, 0.075 * r, 16), BLUSH, flat);
    ctx.globalAlpha = 1;
    eyesAndBrows(fx, hcy - 0.06 * r, [fx - 0.32 * r, fx + 0.32 * r]);
    const nx = mx + f * (sp === "fox" ? 0.34 : 0.18) * r;
    part("nose", ell(nx, my - 0.12 * r, (sp === "bear" ? 0.15 : 0.11) * r, (sp === "bear" ? 0.11 : 0.08) * r, 14), INK, { shadow: false, edge: 0 });
    if (sp === "cat" || sp === "rabbit" || sp === "fox") {
      ctx.save();
      ctx.globalAlpha = 0.55;
      ctx.strokeStyle = INK;
      ctx.lineWidth = 0.022 * r * u;
      for (const side of [-1, 1]) {
        for (let k = -1; k <= 1; k++) {
          ctx.beginPath();
          ctx.moveTo((mx + side * 0.22 * r) * u, (my + k * 0.06 * r) * u);
          ctx.lineTo((mx + side * 0.72 * r) * u, (my + k * 0.14 * r - 0.02 * r) * u);
          ctx.stroke();
        }
      }
      ctx.restore();
    }
    mouth(mx, my + 0.12 * r);
  }

  function drawTail() {
    const sp = look.species;
    const fur = look.skin;
    const hy = B.hipY;
    const back = -B.hh; // (hh isn't set yet: the tail is drawn before the hips)
    if (sp === "fox") {
      part("tail", scaled([[back * 0.6, hy - 0.03], [back * 1.5, hy - 0.12], [back * 2.6, hy - 0.06], [back * 3.1, hy + 0.08], [back * 2.3, hy + 0.13], [back * 1.3, hy + 0.08]]), fur);
      part("tail-tip", scaled([[back * 2.55, hy - 0.05], [back * 3.1, hy + 0.08], [back * 2.7, hy + 0.12], [back * 2.45, hy + 0.06]]), look.muzzle, { shadow: false });
    } else if (sp === "cat") {
      const pts: Pt[] = [[back * 0.8, hy], [back * 1.8, hy + 0.02], [back * 2.4, hy - 0.1], [back * 2.25, hy - 0.26]];
      for (let i = 0; i < pts.length - 1; i++) {
        part(`tail-${i}`, capsulePts(pts[i][0] * u, pts[i][1] * u, pts[i + 1][0] * u, pts[i + 1][1] * u, 0.035 * u), fur);
      }
    } else {
      part("tail", ell(back * 1.08, hy + 0.01, sp === "rabbit" ? 0.05 : 0.035, sp === "rabbit" ? 0.046 : 0.032, 16), sp === "rabbit" ? look.muzzle : fur);
    }
  }

  // ================================================================ hair
  // arc of the head outline, angles in degrees (0 = right, 90 = down, 270 = top)
  function arcPts(a0: number, a1: number, R: number, cy = hcy): Pt[] {
    const pts: Pt[] = [];
    for (let i = 0; i <= 20; i++) {
      const a = (a0 + ((a1 - a0) * i) / 20) * RAD;
      pts.push([Math.cos(a) * R, cy + Math.sin(a) * R]);
    }
    return pts;
  }

  function capShape(): Pt[] {
    // hair over the top of the head with a fringe; the back comes lower in 3/4 view
    if (f) {
      return [...arcPts(150, 345, r * 1.08), [0.62 * r, hcy - 0.42 * r], [0.25 * r, hcy - 0.5 * r], [-0.2 * r, hcy - 0.42 * r], [-0.55 * r, hcy - 0.18 * r], [-0.72 * r, hcy + 0.25 * r]];
    }
    return [...arcPts(185, 355, r * 1.08), [0.8 * r, hcy - 0.3 * r], [0.4 * r, hcy - 0.5 * r], [0, hcy - 0.44 * r], [-0.4 * r, hcy - 0.5 * r], [-0.8 * r, hcy - 0.3 * r]];
  }

  function hairBack() {
    const c = look.hair.color;
    const s = hairOf;
    if (look.hat?.style === "knight-helmet") {
      // chain mail hanging from the helmet to the shoulders
      part("mail", roundRectPts(-1.12 * r * u, (hcy - 0.5 * r) * u, 2.24 * r * u, 1.62 * r * u, 0.42 * r * u), shade(look.hat.color, -0.1));
      return;
    }
    if (look.hat?.style === "nemes") {
      const back = scaled([[-1.1 * r - f * 0.15 * r, hcy - 0.5 * r], [1.1 * r - f * 0.15 * r, hcy - 0.5 * r], [1.5 * r - f * 0.2 * r, hcy + 1.4 * r], [-1.5 * r - f * 0.2 * r, hcy + 1.4 * r]]);
      striped("nemes-back", back, look.hat.color, "#2f5d9a", 7);
      return;
    }
    if (s === "long" || s === "braids") part("hair-back", roundRectPts(-1.15 * r * u, (hcy - 0.7 * r) * u, 2.3 * r * u, 2.25 * r * u, 0.6 * r * u), c);
    if (s === "bob") part("hair-back", roundRectPts(-1.18 * r * u, (hcy - 0.75 * r) * u, 2.36 * r * u, 1.72 * r * u, 0.55 * r * u), c);
    if (s === "afro") part("hair-back", ell(0, hcy - 0.18 * r, r * 1.45, r * 1.38, 40), c);
    if (s === "bun") part("bun", ell(-f * 0.25 * r, hcy - 1.08 * r, 0.42 * r, 0.38 * r, 24), c);
    if (s === "ponytail") part("tail", capsulePts(-(f ? 0.85 : 0.75) * r * u, (hcy - 0.45 * r) * u, -(f ? 1.25 : 1.05) * r * u, (hcy + 0.95 * r) * u, 0.42 * r * u), c);
    if (s === "headscarf") {
      group("scarf-back", [ell(0, hcy, r * 1.24, r * 1.22, 40), scaled([[-1.05 * r, hcy + 0.4 * r], [1.05 * r, hcy + 0.4 * r], [1.5 * r, hcy + 1.75 * r], [-1.5 * r, hcy + 1.75 * r]])], look.accent);
    }
  }

  function hairFront() {
    const c = look.hair.color;
    const s = hairOf;
    if (s === "bald") return;
    if (s === "balding") {
      part("tuft-back", ell(-(f ? 0.9 : 0.95) * r, hcy + 0.02 * r, 0.2 * r, 0.3 * r, 16), c);
      if (!f) part("tuft-front", ell(0.95 * r, hcy + 0.02 * r, 0.2 * r, 0.3 * r, 16), c);
      return;
    }
    if (s === "headscarf") {
      // a wrap framing the face
      const fx = f * 0.12 * r;
      const outer = arcPts(140, 400, r * 1.14);
      const inner: Pt[] = [];
      for (let i = 20; i >= 0; i--) {
        const a = (150 + (i / 20) * 240) * RAD;
        inner.push([fx + Math.cos(a) * r * 0.86, hcy + 0.05 * r + Math.sin(a) * r * 0.9]);
      }
      part("scarf-wrap", scaled([...outer, ...inner]), look.accent);
      return;
    }
    if (s === "afro") {
      group("afro-front", arcPts(200, 340, r * 0.95).filter((_, i) => i % 4 === 0).map(([x, y]) => ell(x, y, 0.28 * r, 0.26 * r, 16)), c, { shadow: false });
      return;
    }
    if (s === "curly") {
      const puffs = arcPts(f ? 160 : 190, f ? 345 : 350, r * 0.98).filter((_, i) => i % 3 === 0).map(([x, y]) => ell(x, y, 0.3 * r, 0.28 * r, 16));
      group("curls", [capShape(), ...puffs], c);
      return;
    }
    if (s === "spiky") {
      const spikes: Pt[][] = [];
      for (let i = 0; i < 6; i++) {
        const a = (200 + i * 28) * RAD;
        const bx = Math.cos(a) * r, byy = hcy + Math.sin(a) * r;
        spikes.push([[bx - 0.18 * r, byy + 0.05 * r], [Math.cos(a) * r * 1.45, hcy + Math.sin(a) * r * 1.45], [bx + 0.18 * r, byy + 0.05 * r]]);
      }
      group("spikes", [capShape(), ...spikes], c);
      return;
    }
    if (s === "long" || s === "braids" || s === "bob") {
      // centre-parted top that falls past the ears
      const fringe: Pt[] =
        s === "bob"
          ? [[0.9 * r, hcy + 0.15 * r], [0.6 * r, hcy - 0.32 * r], [-0.6 * r, hcy - 0.32 * r], [-0.9 * r, hcy + 0.15 * r]] // straight bangs
          : [[0.85 * r, hcy + 0.35 * r], [0.55 * r, hcy - 0.35 * r], [0.05 * r, hcy - 0.62 * r], [-0.5 * r, hcy - 0.35 * r], [-0.85 * r, hcy + 0.35 * r]];
      const pts: Pt[] = [...arcPts(165, 375, r * 1.1), ...fringe];
      part("hair-top", scaled(pts), c);
      if (s === "braids") {
        for (const side of [-1, 1]) {
          const beads: Pt[][] = [];
          for (let i = 0; i < 6; i++) beads.push(ell(side * (0.95 + i * 0.02) * r, hcy + (0.35 + i * 0.22) * r, 0.16 * r, 0.13 * r, 14));
          group(`braid-${side}`, beads, c);
        }
      }
      return;
    }
    // short, side-part, bun, ponytail
    const shapes: Pt[][] = [capShape()];
    if (s === "side-part") shapes.push(ell(0.25 * r, hcy - 0.72 * r, 0.62 * r, 0.3 * r, 24));
    group("hair", shapes.map((pts) => scaled(pts)), c);
  }

  // a shape filled in one colour with horizontal bands of another
  function striped(name: string, pts: Pt[], base: string, band: string, bands: number) {
    part(name, pts, base);
    let y0 = Infinity, y1 = -Infinity, x0 = Infinity, x1 = -Infinity;
    for (const [x, y] of pts) {
      y0 = Math.min(y0, y); y1 = Math.max(y1, y);
      x0 = Math.min(x0, x); x1 = Math.max(x1, x);
    }
    ctx.save();
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.clip();
    const step = (y1 - y0) / (bands * 2);
    for (let k = 0; k < bands; k++) part(`${name}-band-${k}`, rectPts(x0 - 4, y0 + (k * 2 + 1) * step, x1 - x0 + 8, step), band, flat);
    ctx.restore();
  }

  // ================================================================ hats
  function drawHat() {
    if (!look.hat) return;
    const c = look.hat.color;
    const band = shade(c, -0.15);
    const half = (cx: number, cy: number, rx: number, ry: number): Pt[] => arcPts(180, 360, 1).map(([x, y]) => [cx + x * rx, cy + (y - hcy) * ry]);
    switch (look.hat.style) {
      case "fedora":
        part("hat-crown", scaled([[-0.72 * r, hcy - 0.72 * r], [0.72 * r, hcy - 0.72 * r], [0.6 * r, hcy - 1.36 * r], [0.05 * r, hcy - 1.24 * r], [-0.6 * r, hcy - 1.36 * r]]), c);
        part("hat-band", rectPts(-0.7 * r * u, (hcy - 0.92 * r) * u, 1.4 * r * u, 0.17 * r * u), band, { shadow: false });
        part("hat-brim", ell(f * 0.06 * r, hcy - 0.74 * r, 1.32 * r, 0.16 * r, 32), c);
        break;
      case "bowler":
        part("hat-crown", scaled(half(0, hcy - 0.72 * r, 0.8 * r, 0.62 * r)), c);
        part("hat-brim", ell(0, hcy - 0.74 * r, 1.08 * r, 0.13 * r, 32), c);
        break;
      case "tophat":
        part("hat-crown", rectPts(-0.62 * r * u, (hcy - 1.8 * r) * u, 1.24 * r * u, 1.08 * r * u), c);
        part("hat-band", rectPts(-0.62 * r * u, (hcy - 0.95 * r) * u, 1.24 * r * u, 0.18 * r * u), look.accent, { shadow: false });
        part("hat-brim", ell(0, hcy - 0.74 * r, 1.08 * r, 0.13 * r, 32), c);
        break;
      case "cap":
        part("hat-crown", scaled(half(0, hcy - 0.38 * r, 1.04 * r, 0.8 * r)), c);
        part("hat-brim", f ? ell(0.95 * r, hcy - 0.42 * r, 0.6 * r, 0.12 * r, 24) : ell(0, hcy - 0.4 * r, 0.85 * r, 0.2 * r, 24), shade(c, -0.08));
        break;
      case "crown": {
        const pts: Pt[] = [[-0.75 * r, hcy - 0.62 * r]];
        for (let i = 0; i <= 4; i++) {
          const x = -0.75 * r + (i / 4) * 1.5 * r;
          pts.push([x, hcy - (i % 2 ? 1.02 : 1.32) * r]);
        }
        pts.push([0.75 * r, hcy - 0.62 * r]);
        part("crown", scaled(pts), c);
        part("crown-gem", ell(0, hcy - 0.78 * r, 0.1 * r, 0.1 * r, 12), "#d1495b", { shadow: false });
        break;
      }
      case "beanie":
        part("hat-crown", scaled(half(0, hcy - 0.25 * r, 1.08 * r, 0.98 * r)), c);
        part("hat-fold", roundRectPts(-1.08 * r * u, (hcy - 0.5 * r) * u, 2.16 * r * u, 0.3 * r * u, 0.1 * r * u), band);
        part("hat-pom", ell(0, hcy - 1.25 * r, 0.2 * r, 0.2 * r, 16), look.accent);
        break;
      case "straw":
        part("hat-brim", ell(0, hcy - 0.62 * r, 1.6 * r, 0.22 * r, 36), c);
        part("hat-crown", scaled(half(0, hcy - 0.66 * r, 0.72 * r, 0.52 * r)), c);
        part("hat-band", rectPts(-0.72 * r * u, (hcy - 0.8 * r) * u, 1.44 * r * u, 0.14 * r * u), look.accent, { shadow: false });
        break;
      case "helmet":
        part("hat-crown", scaled(half(0, hcy - 0.2 * r, 1.14 * r, 1.08 * r)), c);
        part("hat-rim", roundRectPts(-1.2 * r * u, (hcy - 0.3 * r) * u, 2.4 * r * u, 0.14 * r * u, 0.06 * r * u), shade(c, -0.1));
        break;
      case "space-helmet": {
        // a clear bubble: the face shows through
        const R = r * 1.42;
        const cy = hcy + 0.05 * r;
        ctx.save();
        ctx.globalAlpha = 0.16;
        ctx.fillStyle = "#cfe8ff";
        ctx.beginPath();
        ctx.arc(0, cy * u, R * u, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
        part("bubble-rim", [...ell(0, cy, R, R, 40), ...ell(0, cy, R * 0.93, R * 0.93, 40).reverse()], c, { shadow: false });
        ctx.save();
        ctx.strokeStyle = "rgba(255,255,255,0.75)";
        ctx.lineWidth = 0.08 * r * u;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.arc(0, cy * u, R * 0.78 * u, 1.15 * Math.PI, 1.45 * Math.PI);
        ctx.stroke();
        ctx.restore();
        break;
      }
      case "knight-helmet": {
        const nx = f * 0.12 * r;
        part("plume", scaled([[0, hcy - 1.1 * r], [0.22 * r, hcy - 1.45 * r], [-0.3 * r, hcy - 1.64 * r], [-0.95 * r, hcy - 1.38 * r], [-1.32 * r, hcy - 0.86 * r], [-0.9 * r, hcy - 1.05 * r], [-0.35 * r, hcy - 1.16 * r]]), look.accent);
        part("helm-dome", scaled(half(0, hcy - 0.16 * r, 1.13 * r, 1.0 * r)), c);
        if (f) part("helm-cheek", scaled([[-1.12 * r, hcy - 0.2 * r], [-0.52 * r, hcy - 0.2 * r], [-0.58 * r, hcy + 0.55 * r], [-1.02 * r, hcy + 0.5 * r]]), c);
        else for (const side of [-1, 1]) part(`helm-cheek-${side}`, scaled([[side * 1.13 * r, hcy - 0.2 * r], [side * 0.8 * r, hcy - 0.2 * r], [side * 0.8 * r, hcy + 0.55 * r], [side * 1.06 * r, hcy + 0.5 * r]]), c);
        part("helm-rim", roundRectPts(-1.16 * r * u, (hcy - 0.3 * r) * u, 2.32 * r * u, 0.16 * r * u, 0.06 * r * u), band);
        part("helm-nose", rectPts((nx - 0.05 * r) * u, (hcy - 0.3 * r) * u, 0.1 * r * u, 0.5 * r * u), band);
        break;
      }
      case "nemes": {
        // the striped royal headcloth, its headband, the lappets and the cobra
        striped("nemes-cap", scaled(half(0, hcy - 0.18 * r, 1.14 * r, 1.02 * r)), c, "#2f5d9a", 3);
        const laps = f ? [-1] : [-1, 1];
        for (const side of laps) {
          const xa = f ? -0.95 * r : side * 0.84 * r;
          const xb = f ? -0.55 * r : side * 1.2 * r;
          striped(`lappet-${side}`, scaled([[xa, hcy - 0.2 * r], [xb, hcy - 0.2 * r], [xb + side * 0.05 * r, hcy + 1.45 * r], [xa + side * 0.02 * r, hcy + 1.45 * r]]), c, "#2f5d9a", 5);
        }
        part("nemes-band", roundRectPts(-1.16 * r * u, (hcy - 0.32 * r) * u, 2.32 * r * u, 0.14 * r * u, 0.05 * r * u), "#e8b54a");
        const ux = f * 0.18 * r;
        part("uraeus", ell(ux, hcy - 0.36 * r, 0.07 * r, 0.12 * r, 14), "#e8b54a");
        part("uraeus-head", ell(ux, hcy - 0.5 * r, 0.06 * r, 0.05 * r, 12), shade("#e8b54a", -0.1), { shadow: false });
        break;
      }
    }
  }
}
