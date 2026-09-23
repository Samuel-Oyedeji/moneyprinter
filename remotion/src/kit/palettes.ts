import type { Extra, Sky } from "../types";

// One palette per sky. Grounds, towns and interiors take their colours from
// the sky they sit under, so every scene hangs together without the story
// file having to name a single colour.

export type Palette = {
  sky: string;
  bands: { y: number; h: number; c: string }[]; // torn strips across the sky (y, h as frame fractions)
  hills: [string, string, string]; // far, mid, near
  houses: string[];
  roof: string;
  windowLit: string;
  street: string;
  sea: [string, string, string];
  field: string;
  grass: string;
  trunk: string;
  leaf: string;
  cloud: string;
  sun: string;
  moon: string;
  star: string;
  ink: string; // text and faces
  accent: string; // titles, stamps, highlighted caption word
  wall: string;
  wallStripe: string;
  floor: string;
  floorPlank: string;
  wood: string;
  rain: string;
};

const base: Palette = {
  sky: "#9dd0ea",
  bands: [
    { y: 0.2, h: 0.06, c: "#b3dbef" },
    { y: 0.4, h: 0.07, c: "#c4e3f1" },
  ],
  hills: ["#a8cf86", "#86b966", "#5f9a4f"],
  houses: ["#e07a5f", "#f2cc8f", "#81b29a", "#e9a15b", "#6c8ebf"],
  roof: "#8e4b3e",
  windowLit: "#fbf3d6",
  street: "#c9b28f",
  sea: ["#6fb3de", "#4f9bd1", "#3677b3"],
  field: "#9bc36b",
  grass: "#6fa85a",
  trunk: "#7a5238",
  leaf: "#5f9a4f",
  cloud: "#fbf6ea",
  sun: "#f4b642",
  moon: "#f3e6b8",
  star: "#f5d77a",
  ink: "#2b2230",
  accent: "#d1495b",
  wall: "#7fa7a0",
  wallStripe: "#8bb2ab",
  floor: "#a8714f",
  floorPlank: "#96623f",
  wood: "#8a5a3c",
  rain: "#dfe9f2",
};

export const PALETTES: Record<Sky, Palette> = {
  day: base,
  dusk: {
    ...base,
    sky: "#4b3f72",
    bands: [
      { y: 0.14, h: 0.07, c: "#6b4f8a" },
      { y: 0.28, h: 0.08, c: "#a45a8a" },
      { y: 0.4, h: 0.09, c: "#e0726a" },
      { y: 0.5, h: 0.1, c: "#f3a35f" },
    ],
    hills: ["#8a5a86", "#6d4c7d", "#4f3a63"],
    houses: ["#6d4c7d", "#824f78", "#5b3f6e", "#9a5a74"],
    roof: "#3f2b52",
    windowLit: "#f7c65a",
    street: "#5b4566",
    field: "#6d4c7d",
    grass: "#553a66",
    trunk: "#3f2b52",
    leaf: "#553a66",
    cloud: "#f2b8a0",
    sun: "#f06b4f",
    accent: "#f06b4f",
  },
  night: {
    ...base,
    sky: "#1c1f5e",
    bands: [
      { y: 0.14, h: 0.06, c: "#262a78" },
      { y: 0.3, h: 0.055, c: "#262a78" },
    ],
    hills: ["#2f2a70", "#28235f", "#1f1b4d"],
    houses: ["#2b2462", "#3a2f78"],
    roof: "#221c52",
    windowLit: "#f5c85a",
    street: "#2a2560",
    sea: ["#27307a", "#20286a", "#191f55"],
    field: "#28235f",
    grass: "#201c52",
    trunk: "#1d1848",
    leaf: "#2a2a6e",
    cloud: "#3a3f8a",
    accent: "#f5c85a",
  },
  storm: {
    ...base,
    sky: "#5c6b7a",
    bands: [
      { y: 0.12, h: 0.07, c: "#4f5d6b" },
      { y: 0.3, h: 0.08, c: "#687888" },
    ],
    hills: ["#58705a", "#48604b", "#3a4f3d"],
    houses: ["#6b7280", "#7c6f64", "#5f6b73"],
    roof: "#3d434b",
    windowLit: "#f2d58a",
    street: "#5a5e63",
    sea: ["#4c6372", "#3e5463", "#314553"],
    field: "#56705a",
    grass: "#46604b",
    leaf: "#3f5a45",
    cloud: "#414b56",
    accent: "#e9a15b",
  },
  parchment: {
    ...base,
    sky: "#efe2c4",
    bands: [
      { y: 0.16, h: 0.05, c: "#e8d7b3" },
      { y: 0.78, h: 0.06, c: "#e8d7b3" },
    ],
    ink: "#3b2f2a",
    accent: "#c8553d",
  },
  room: {
    ...base,
    sky: "#7fa7a0",
    bands: [],
  },
};

export function defaultExtras(sky: Sky): Extra[] {
  switch (sky) {
    case "day":
      return [{ type: "sun", x: 0.8, y: 0.12, size: 1 }, { type: "clouds", count: 3 }];
    case "dusk":
      return [{ type: "sun", x: 0.3, y: 0.46, size: 1.3 }, { type: "clouds", count: 2 }];
    case "night":
      return [{ type: "stars" }, { type: "moon", x: 0.2, y: 0.1 }];
    case "storm":
      return [{ type: "clouds", count: 4 }, { type: "rain" }];
    case "room":
      return [{ type: "window", x: 0.74, y: 0.3 }];
    default:
      return [];
  }
}
