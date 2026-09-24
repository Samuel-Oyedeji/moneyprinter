import { shade } from "../kit/paper";
import type { Accessory, BottomStyle, Character, HairStyle, HatStyle, Kind, Skin, Species, TopStyle } from "../types";

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
  "space-helmet": "#e8ecf0",
  "knight-helmet": "#aab4be",
  nemes: "#e8b54a",
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
  spacesuit: "#eef1f4",
  armor: "#aab4be",
  bare: "#d9a57b",
  robot: "#b8c4cc",
};

// Storybook animal colours: fur, the lighter muzzle, the inside of the ears.
export const SPECIES_FUR: Record<Species, { fur: string; muzzle: string; ear: string }> = {
  fox: { fur: "#e07a3f", muzzle: "#f6ead8", ear: "#3b2a24" },
  rabbit: { fur: "#d8d2cb", muzzle: "#f4efe9", ear: "#f2b5b5" },
  bear: { fur: "#8a5a3c", muzzle: "#c9a07c", ear: "#6b432b" },
  cat: { fur: "#8f96a0", muzzle: "#ece8e2", ear: "#f2b5b5" },
};

export type Look = {
  kind: Kind;
  species: Species;
  muzzle: string; // animals
  earInner: string; // animals
  hands: string; // skin, gloves or gauntlets
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
  const base = personLook(c);
  const kind = c?.kind ?? "person";
  const accent = base.accent;
  switch (kind) {
    case "astronaut":
      return {
        ...base,
        top: { style: "spacesuit", color: "#eef1f4", inner: accent },
        bottom: { style: "trousers", color: "#e3e7ec" },
        shoes: "#9aa3ad",
        hands: "#d5dbe1",
        hat: { style: "space-helmet", color: "#e8ecf0" },
      };
    case "knight": {
      const metal = "#aab4be";
      return {
        ...base,
        // the tabard over the armour takes the top colour
        top: { style: "armor", color: metal, inner: hex(c?.top?.color, accent) },
        bottom: { style: "trousers", color: shade(metal, -0.06) },
        shoes: shade(metal, -0.14),
        hands: shade(metal, -0.04),
        hat: { style: "knight-helmet", color: metal },
      };
    }
    case "pharaoh": {
      const skin = c?.skin ? base.skin : SKINS.tan;
      return {
        ...base,
        skin,
        hands: skin,
        facialHair: "none",
        top: { style: "bare", color: skin, inner: skin },
        bottom: { style: "kilt", color: "#f4efe0" },
        shoes: "#8a5a3c",
        hat: { style: "nemes", color: "#e8b54a" },
        acc: new Set([...base.acc, "collar"]),
      };
    }
    case "robot": {
      const metal = hex(c?.top?.color, "#b8c4cc");
      return {
        ...base,
        skin: metal,
        hands: shade(metal, -0.08),
        hair: { style: "bald", color: metal },
        facialHair: "none",
        top: { style: "robot", color: metal, inner: accent },
        bottom: { style: "trousers", color: shade(metal, -0.06) },
        shoes: "#4a5560",
        hat: undefined,
      };
    }
    case "animal": {
      const species: Species = c?.species ?? "fox";
      const sp = SPECIES_FUR[species];
      const fur = hex(c?.fur, sp.fur);
      return {
        ...base,
        species,
        skin: fur,
        hands: fur,
        muzzle: sp.muzzle,
        earInner: sp.ear,
        hair: { style: "bald", color: fur },
        facialHair: "none",
        top: c?.top ? base.top : { style: "tshirt", color: "#81b29a", inner: "#f4f1ea" },
        bottom: c?.bottom ? base.bottom : { style: "shorts", color: "#3d405b" },
        shoes: shade(fur, -0.12),
      };
    }
    default:
      return base;
  }
}

function personLook(c: Character | undefined): Look {
  const age = c?.age ?? "adult";
  const skin = c?.skin && c.skin in SKINS ? SKINS[c.skin as Skin] : hex(c?.skin, SKINS.fair);
  const topStyle = c?.top?.style ?? "shirt";
  return {
    kind: c?.kind ?? "person",
    species: c?.species ?? "fox",
    muzzle: "#f6ead8",
    earInner: "#f2b5b5",
    hands: skin,
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
