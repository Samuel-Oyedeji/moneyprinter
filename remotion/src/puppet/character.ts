import type { Accessory, BottomStyle, Character, HairStyle, HatStyle, Skin, TopStyle } from "../types";

// Resolves a cast entry into concrete colours and body proportions. All
// lengths are fractions of the person's full height (feet at 0, top of the
// head at -1; y grows downward like the canvas).

export const SKINS: Record<Skin, string> = {
  light: "#f6d3b8",
  fair: "#efc4a1",
  tan: "#d9a57b",
  brown: "#b07a52",
  dark: "#7a4b2e",
  deep: "#5a3520",
};

const HAT_COLORS: Record<HatStyle, string> = {
  fedora: "#6b4f3a",
  bowler: "#2e2a33",
  tophat: "#2e2a33",
  cap: "#d1495b",
  crown: "#f2c14e",
  beanie: "#4f7fbf",
  straw: "#e3c07a",
  helmet: "#7d868c",
};

const TOP_COLORS: Record<TopStyle, string> = {
  shirt: "#6c8ebf",
  tshirt: "#e07a5f",
  sweater: "#81b29a",
  suit: "#4a4e69",
  labcoat: "#f4f1ea",
  coat: "#8e5b3e",
  dress: "#d1495b",
  robe: "#6d4c7d",
};

export type Look = {
  skin: string;
  hair: { style: HairStyle; color: string };
  facialHair: "none" | "mustache" | "beard" | "goatee";
  top: { style: TopStyle; color: string; inner: string };
  bottom: { style: BottomStyle; color: string };
  shoes: string;
  hat?: { style: HatStyle; color: string };
  acc: Set<Accessory>;
  accent: string;
};

export type Body = {
  headR: number;
  headCY: number;
  shoulderY: number;
  hipY: number;
  sh: number; // half shoulder width
  hh: number; // half hip width
  armUp: number;
  armLo: number;
  armW: number;
  handR: number;
  legUp: number;
  legLo: number;
  legW: number;
  legX: number;
  shoeL: number;
  shoeH: number;
  neckW: number;
  lean: number; // degrees, elders stoop a little
};

const hex = (c: string | undefined, fallback: string) => (c && /^#[0-9a-f]{6}$/i.test(c) ? c : fallback);

export function lookOf(c: Character | undefined): Look {
  const age = c?.age ?? "adult";
  const skin = c?.skin && c.skin in SKINS ? SKINS[c.skin as Skin] : hex(c?.skin, SKINS.fair);
  const topStyle = c?.top?.style ?? "shirt";
  return {
    skin,
    hair: { style: c?.hair?.style ?? (age === "elder" ? "balding" : "short"), color: hex(c?.hair?.color, age === "elder" ? "#cfc9c2" : "#4a3426") },
    facialHair: c?.facialHair ?? "none",
    top: {
      style: topStyle,
      color: hex(c?.top?.color, TOP_COLORS[topStyle]),
      inner: hex(c?.top?.inner, topStyle === "labcoat" || topStyle === "coat" ? "#6b4f3a" : "#f4f1ea"),
    },
    bottom: { style: c?.bottom?.style ?? "trousers", color: hex(c?.bottom?.color, "#3d405b") },
    shoes: hex(c?.shoes, "#3b2f2a"),
    hat: c?.hat ? { style: c.hat.style, color: hex(c.hat.color, HAT_COLORS[c.hat.style]) } : undefined,
    acc: new Set(c?.accessories ?? []),
    accent: hex(c?.accent, "#d1495b"),
  };
}

export function bodyOf(c: Character | undefined): Body {
  const age = c?.age ?? "adult";
  const width = c?.build === "slim" ? 0.86 : c?.build === "broad" ? 1.2 : 1;
  if (age === "child") {
    return {
      headR: 0.165, headCY: -0.835, shoulderY: -0.64, hipY: -0.36,
      sh: 0.13 * width, hh: 0.11 * width,
      armUp: 0.14, armLo: 0.13, armW: 0.07, handR: 0.036,
      legUp: 0.18, legLo: 0.155, legW: 0.08, legX: 0.052,
      shoeL: 0.1, shoeH: 0.038, neckW: 0.07, lean: 0,
    };
  }
  return {
    headR: 0.135, headCY: -0.865, shoulderY: -0.715, hipY: -0.4,
    sh: 0.15 * width, hh: 0.125 * width,
    armUp: 0.165, armLo: 0.15, armW: 0.062, handR: 0.033,
    legUp: 0.2, legLo: 0.178, legW: 0.074, legX: 0.058,
    shoeL: 0.095, shoeH: 0.034, neckW: 0.065, lean: age === "elder" ? 4 : 0,
  };
}
