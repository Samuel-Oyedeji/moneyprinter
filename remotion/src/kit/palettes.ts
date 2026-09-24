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
  sand: [string, string, string]; // far, mid, near
  rock: string;
  snowHills: [string, string, string];
  pine: [string, string];
  city: [string, string];
  stone: string; // castles, temples
  lunar: [string, string, string];
  board: string; // classroom chalkboard
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
  sand: ["#f1d49a", "#e8bf78", "#d9a35c"],
  rock: "#8d8a86",
  snowHills: ["#d5e0ec", "#e4ebf4", "#f3f7fb"],
  pine: ["#7aa487", "#4f8161"],
  city: ["#a9bccd", "#8199b0"],
  stone: "#b3a795",
  lunar: ["#a8a49c", "#bdb9b1", "#8f8b84"],
  board: "#2f5a47",
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
    sand: ["#c28a8f", "#a8737f", "#8b5f70"],
    rock: "#5b4566",
    snowHills: ["#a996bd", "#bba8cb", "#cdbcd8"],
    pine: ["#5b3f6e", "#472f5c"],
    city: ["#5e4870", "#4a3857"],
    stone: "#7d6479",
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
    sand: ["#3f3a78", "#35306a", "#2b2758"],
    rock: "#2a2560",
    snowHills: ["#39408a", "#454d9a", "#5259a8"],
    pine: ["#262a6e", "#1d205a"],
    city: ["#2a2e72", "#21245e"],
    stone: "#3a3478",
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
    sand: ["#b8a37f", "#a38f6c", "#8d7b5c"],
    snowHills: ["#b9c1ca", "#c7ced6", "#d6dce2"],
    pine: ["#4a6450", "#3a5240"],
    city: ["#6b7684", "#5b6674"],
    stone: "#7d7a74",
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
  dawn: {
    ...base,
    sky: "#f6d7b8",
    bands: [
      { y: 0.1, h: 0.06, c: "#f2bfae" },
      { y: 0.24, h: 0.07, c: "#f8cc98" },
      { y: 0.38, h: 0.08, c: "#fbe3ad" },
    ],
    hills: ["#b8cc8f", "#97b774", "#76a05c"],
    sun: "#f59a54",
    cloud: "#fff3e4",
    accent: "#e0645a",
    sea: ["#94c4dc", "#72aacd", "#4f89b4"],
    windowLit: "#fbe9b8",
    sand: ["#f5d7a4", "#ecc285", "#dfa86a"],
    city: ["#c9b8c2", "#a998a8"],
  },
  space: {
    ...base,
    sky: "#10133a",
    bands: [],
    star: "#fbe7a1",
    moon: "#e6dfcf",
    cloud: "#2a2f6e",
    accent: "#f5c85a",
  },
  underwater: {
    ...base,
    sky: "#2b78a8",
    bands: [
      { y: -0.05, h: 0.12, c: "#4f9fcb" },
      { y: 0.14, h: 0.08, c: "#3f8dbd" },
      { y: 0.38, h: 0.1, c: "#2a6b9a" },
      { y: 0.58, h: 0.12, c: "#235d88" },
    ],
    accent: "#f2b35b",
    sand: ["#c4b187", "#d6c294", "#e3d0a2"],
    rock: "#3d6a80",
  },
  classroom: {
    ...base,
    sky: "#eadcb4",
    bands: [],
    wall: "#eadcb4",
    wallStripe: "#e2d1a1",
    floor: "#b07a52",
    floorPlank: "#9c6a45",
  },
  lab: {
    ...base,
    sky: "#dce8eb",
    bands: [],
    wall: "#dce8eb",
    wallStripe: "#c6d6da",
    floor: "#9aa7ae",
    floorPlank: "#8a979e",
    wood: "#9b7653",
  },
  hall: {
    ...base,
    sky: "#8e8579",
    bands: [],
    wall: "#8e8579",
    wallStripe: "#80776c",
    floor: "#6d655c",
    floorPlank: "#61594f",
    wood: "#6b4a33",
    accent: "#b8322e",
  },
};

// Settings with their own walls and floor.
export const INTERIORS: Sky[] = ["room", "classroom", "lab", "hall"];

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
    case "dawn":
      return [{ type: "sun", x: 0.74, y: 0.4, size: 1.1 }, { type: "clouds", count: 2 }, { type: "birds", count: 3 }];
    case "space":
      return [{ type: "stars" }, { type: "planet", x: 0.76, y: 0.2 }];
    case "underwater":
      return [{ type: "fish", count: 5 }, { type: "bubbles" }];
    default:
      return [];
  }
}
