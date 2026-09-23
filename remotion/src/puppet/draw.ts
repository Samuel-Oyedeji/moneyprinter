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
  withHead(() => hairBack());

  // ---------------------------------------------------------------- legs
  const legColor = look.bottom.style === "trousers" && top !== "robe" && top !== "dress" ? look.bottom.color : look.skin;
  for (const [name, L, hipX] of [["legB", legB, -B.legX], ["legF", legF, B.legX]] as const) {
    part(`${name}-thigh`, capsulePts(hipX * u, B.hipY * u, L.ex * u, L.ey * u, B.legW * u), legColor, { angle: Math.PI / 2 });
    part(`${name}-shin`, capsulePts(L.ex * u, L.ey * u, L.hx * u, L.hy * u, B.legW * 0.92 * u), legColor, { angle: Math.PI / 2 });
    if (look.bottom.style === "shorts" && top !== "robe" && top !== "dress") {
      const mx = hipX + (L.ex - hipX) * 0.55, my = B.hipY + (L.ey - B.hipY) * 0.55;
      part(`${name}-shorts`, capsulePts(hipX * u, B.hipY * u, mx * u, my * u, B.legW * 1.15 * u), look.bottom.color);
    }
    const shoeX = L.hx + f * B.shoeL * 0.32;
    part(`${name}-shoe`, ell(shoeX, L.hy + B.shoeH * 0.35, B.shoeL * (f ? 0.55 : 0.42), B.shoeH), look.shoes);
  }

  // ---------------------------------------------------------------- hips & skirts
  const hh = B.hh;
  if (top === "robe") {
    part("robe-skirt", scaled([[-hh, B.hipY - 0.04], [hh, B.hipY - 0.04], [hh * 1.4, -0.045], [-hh * 1.4, -0.045]]), look.top.color, { angle: Math.PI / 2 });
  } else if (top === "dress") {
    part("dress-skirt", scaled([[-hh, B.hipY - 0.04], [hh, B.hipY - 0.04], [hh * 1.55, B.hipY + 0.2], [-hh * 1.55, B.hipY + 0.2]]), look.top.color);
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
    const ears = !["long", "bob", "afro", "headscarf", "braids"].includes(hairOf);
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
    part(`${name}-fore`, capsulePts(A.ex * u, A.ey * u, A.hx * u, A.hy * u, B.armW * 0.9 * u), longSleeves ? sleeve : look.skin, { angle: Math.PI / 2 });
    if (top === "suit") {
      const kx = A.ex + (A.hx - A.ex) * 0.86, ky = A.ey + (A.hy - A.ey) * 0.86;
      part(`${name}-cuff`, capsulePts(kx * u, ky * u, A.hx * u, A.hy * u, B.armW * 0.85 * u), "#f4f1ea", { shadow: false });
    }
    part(`${name}-hand`, ell(A.hx, A.hy, B.handR, B.handR, 16), look.skin);
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
    const lx = pose.lookX * 0.07 * r, ly = pose.lookY * 0.06 * r;
    const ey = hcy + 0.02 * r;
    const eyes = [fx - 0.32 * r, fx + 0.32 * r];
    // cheeks
    ctx.globalAlpha = 0.5;
    for (const ex of eyes) part(`cheek-${ex > fx}`, ell(ex + (ex > fx ? 0.16 : -0.16) * r, hcy + 0.27 * r, 0.12 * r, 0.075 * r, 16), BLUSH, flat);
    ctx.globalAlpha = 1;
    // nose
    part("nose", ell(fx + f * 0.06 * r, hcy + 0.18 * r, 0.075 * r, 0.06 * r, 12), shade(look.skin, -0.07), flat);
    // eyes
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
    }
    // brows
    const browColor = hairOf === "bald" || hairOf === "balding" ? shade(look.skin, -0.3) : shade(look.hair.color, -0.1);
    ctx.strokeStyle = browColor;
    ctx.lineWidth = 0.05 * r * u;
    const by = hcy - (pose.brows === "raised" ? 0.3 : 0.22) * r;
    for (const ex of eyes) {
      const inner = ex > fx ? -1 : 1; // direction toward the nose
      const tilt = pose.brows === "worried" ? -0.06 : pose.brows === "angry" ? 0.07 : 0;
      ctx.beginPath();
      ctx.moveTo((ex - inner * 0.1 * r) * u, by * u);
      ctx.lineTo((ex + inner * 0.1 * r) * u, (by + tilt * r) * u);
      ctx.stroke();
    }
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
    }
  }
}
