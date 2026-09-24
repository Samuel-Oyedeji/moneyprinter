// The story format. A workflow writes one of these as JSON; the kit turns it
// into video. Everything on screen is drawn in code from named options, so
// an LLM can fill it in without writing drawing code.
//
// Coordinates are fractions of the frame: x 0 = left edge, 1 = right edge;
// y 0 = top, 1 = bottom. Times are seconds. Scene times are relative to the
// scene's own start; caption word times are absolute (they come from TTS).

// Outdoor skies take any outdoor ground; interiors (room, classroom, lab,
// hall) have their own walls and floor; space and underwater have their own
// grounds (lunar, seabed); parchment is a plain board for fact moments.
export type Sky =
  | "day" | "dusk" | "night" | "storm" | "dawn"
  | "parchment"
  | "room" | "classroom" | "lab" | "hall"
  | "space" | "underwater";
export type Ground =
  | "hills" | "town" | "field" | "sea" | "desert" | "forest" | "mountains" | "city" | "beach" | "snowfield"
  | "lunar" | "seabed"
  | "none";

// Landmarks stand on the horizon, behind the near ground.
export type Landmark = "pyramids" | "castle" | "temple" | "lighthouse" | "volcano";

// Code-drawn props that belong to the backdrop.
export type Extra =
  | { type: "sun"; x?: number; y?: number; size?: number; face?: boolean }
  | { type: "moon"; x?: number; y?: number; size?: number }
  | { type: "stars" }
  | { type: "clouds"; count?: number }
  | { type: "rain" }
  | { type: "snow" }
  | { type: "window"; x?: number; y?: number; size?: number }
  | { type: "table"; x?: number; y?: number; width?: number }
  | { type: "tree"; x: number; y?: number; size?: number }
  | { type: "planet"; x?: number; y?: number; size?: number; color?: string }
  | { type: "earth"; x?: number; y?: number; size?: number }
  | { type: "birds"; count?: number } // a flock crossing the sky
  | { type: "fish"; count?: number } // a school swimming past (underwater)
  | { type: "bubbles" }
  | { type: Landmark; x?: number; size?: number };

export type Backdrop = {
  sky: Sky;
  ground?: Ground; // ignored for "room" (it has its own floor) and "parchment"
  extras?: Extra[]; // added to the sky's defaults (night has stars + moon, etc.)
  noDefaults?: boolean; // true = only draw the extras listed here
  seed?: number;
};

// ------------------------------------------------------------ characters

export type Skin = "light" | "fair" | "tan" | "brown" | "dark" | "deep";
export type HairStyle =
  | "short" | "side-part" | "spiky" | "curly" | "afro" | "long" | "bob"
  | "bun" | "ponytail" | "braids" | "balding" | "bald" | "headscarf";
export type HatStyle =
  | "fedora" | "bowler" | "tophat" | "cap" | "crown" | "beanie" | "straw" | "helmet"
  | "space-helmet" | "knight-helmet" | "nemes"; // the last three come with a character kind
export type TopStyle =
  | "shirt" | "tshirt" | "sweater" | "suit" | "labcoat" | "coat" | "dress" | "robe"
  | "spacesuit" | "armor" | "bare" | "robot"; // the last four come with a character kind
export type BottomStyle = "trousers" | "shorts" | "skirt" | "kilt";
export type Accessory = "tie" | "bowtie" | "glasses" | "scarf" | "necklace" | "belt" | "apron" | "cape" | "collar";

// A kind brings its own outfit (and for robots and animals, its own head);
// everything else about the character still applies.
export type Kind = "person" | "astronaut" | "knight" | "pharaoh" | "robot" | "animal";
// Storybook animals stand, talk and wear clothes like people.
export type Species = "fox" | "rabbit" | "bear" | "cat";

// One person, defined once per story and reused in every scene so they
// always look the same. Colours are hex strings; anything left out gets a
// sensible default.
export type Character = {
  id: string;
  kind?: Kind; // default "person"
  species?: Species; // for kind "animal"
  fur?: string; // an animal's colour; each species has its own
  age?: "child" | "adult" | "elder";
  build?: "slim" | "average" | "broad";
  skin?: Skin | string;
  hair?: { style: HairStyle; color?: string };
  facialHair?: "none" | "mustache" | "beard" | "goatee";
  top?: { style: TopStyle; color?: string; inner?: string }; // inner = shirt/vest under a suit or coat
  bottom?: { style: BottomStyle; color?: string };
  shoes?: string;
  hat?: { style: HatStyle; color?: string };
  accessories?: Accessory[];
  accent?: string; // tie, scarf, necklace, cape colour
};

export type Expression = "smile" | "grin" | "neutral" | "frown" | "surprised" | "worried" | "angry" | "sleepy";

export type Enter = "pop" | "slide-left" | "slide-right" | "drop" | "flip" | "none";
export type Exit = "fold" | "slide-left" | "slide-right" | "fly-up";

export type PersonAction =
  | { do: "walk"; at: number; dur: number; to: number } // to = new x
  | { do: "talk"; at: number; dur: number }
  | { do: "point"; at: number; dur?: number }
  | { do: "wave"; at: number; dur?: number }
  | { do: "shrug"; at: number }
  | { do: "think"; at: number; dur?: number }
  | { do: "cheer"; at: number; dur?: number }
  | { do: "nod"; at: number }
  | { do: "shake-head"; at: number }
  | { do: "hop"; at: number }
  | { do: "turn"; at: number } // face the other way
  | { do: "look"; at: number; dir: "left" | "right" | "up" | "down" | "ahead" }
  | { do: "feel"; at: number; face: Expression }; // change expression

// A cast member placed in a scene.
export type Person = {
  who: string; // Character.id
  x: number;
  y: number; // where the feet are
  height?: number; // fraction of frame height, default 0.34 (child 0.24)
  depth?: number;
  facing?: "left" | "right" | "front";
  face?: Expression; // starting expression, default "smile"
  holding?: { prop: PropName; color?: string; pose?: "down" | "up" }; // down = carried at the side, up = held up to look at
  enter?: { type: Enter; at?: number };
  exit?: { type: Exit; at: number };
  actions?: PersonAction[];
};

// ------------------------------------------------------------ props

export type PropName =
  | "book" | "scroll" | "letter" | "coin" | "moneybag" | "crown" | "sword" | "flag"
  | "candle" | "bottle" | "pills" | "cup" | "flask" | "petri-dish" | "dish-stack"
  | "microscope" | "apple" | "basket" | "bucket" | "chest" | "key" | "clock"
  | "hourglass" | "globe" | "lightbulb" | "heart" | "star" | "trophy" | "gift"
  | "suitcase" | "umbrella" | "house" | "boat" | "rock" | "well" | "sign"
  | "chair" | "plant" | "phone" | "laptop" | "arrow" | "shapes";

// A simple shape for the "shapes" prop: coordinates are fractions of the
// prop's box (0,0 top-left, 1,1 bottom-right), for anything not in the list.
export type Shape =
  | { type: "rect"; x: number; y: number; w: number; h: number; color: string; round?: number }
  | { type: "circle"; x: number; y: number; r: number; color: string }
  | { type: "ellipse"; x: number; y: number; rx: number; ry: number; color: string }
  | { type: "poly"; points: [number, number][]; color: string };

export type PropIdle = "breathe" | "sway" | "float" | "still";
export type PropAction =
  | { do: "hop"; at: number }
  | { do: "walk"; at: number; dur: number; to: number }
  | { do: "turn"; at: number }
  | { do: "shake"; at: number; dur?: number }
  | { do: "nod"; at: number }
  | { do: "grow"; at: number; dur?: number }
  | { do: "talk"; at: number; dur: number }
  | { do: "tilt"; at: number; deg?: number }; // lean over and stay leaning

export type Prop = {
  prop: PropName;
  x: number;
  y: number; // where its bottom edge sits
  height: number; // fraction of frame height
  depth?: number;
  color?: string; // main colour; each prop has a default
  color2?: string; // second colour (liquid, label, ribbon...)
  text?: string; // sign, book cover, scroll
  shapes?: Shape[]; // for prop "shapes"
  name?: string; // what a shapes prop is ("tower"), so a transition can find it
  aspect?: number; // for prop "shapes": width / height of its box
  mould?: boolean; // petri-dish: the blue-green mould with its clear ring
  flip?: boolean;
  enter?: { type: Enter; at?: number };
  exit?: { type: Exit; at: number };
  idle?: PropIdle;
  actions?: PropAction[];
};

export type Actor = Person | Prop;
export const isPerson = (a: Actor): a is Person => "who" in a;

// ------------------------------------------------------------ notes, camera

export type Note =
  // Big torn-paper banner near the top of the frame.
  | { kind: "title"; text: string; sub?: string; at?: number; y?: number }
  // A paper badge that slams in: dates, numbers. `count` rolls the number up.
  | {
      kind: "stamp";
      text: string;
      at?: number;
      x?: number;
      y?: number;
      size?: number;
      count?: { from: number; to: number; dur?: number; prefix?: string; suffix?: string; separator?: boolean }; // separator false for years
    }
  // A paper tag on a string, pinned to a point in the scene.
  | { kind: "label"; text: string; at?: number; x: number; y: number; toX: number; toY: number };

export type Camera = {
  move?: "still" | "push" | "pull" | "pan-left" | "pan-right" | "rise" | "drift";
  focusX?: number; // where a push/pull aims
  focusY?: number;
  amount?: number; // 1 = default strength
};

// How a scene arrives. The move straddles the cut: half of it plays over the
// end of the previous scene, half over the start of this one.
export type Transition =
  | "tear" // the old page is ripped away upward
  | "cut"
  | { type: "tear" }
  | { type: "cut" }
  // A paper bird flies at the camera, fills the frame, and swoops past to
  // reveal this scene.
  | { type: "fly"; from?: "left" | "right"; color?: string }
  // A person in the previous scene raises a hand to the camera; their giant
  // palm covers the lens, then sweeps aside. `who` = a cast id in that scene.
  | { type: "hand"; who?: string }
  // The camera flies into a region of the previous scene (a window, a clock
  // face, a book) and this scene is what's inside it. Frame fractions of the
  // previous scene; depth = the layer it sits on (a window is 0.12).
  | {
      type: "zoom";
      // what to fly into: "window", "sun", "moon", "planet", "earth", or a
      // prop (its library name, or the `name` of a shapes prop)
      into?: string;
      // or an explicit region (frame fractions of the previous scene)
      x?: number; y?: number; w?: number; h?: number;
      shape?: "rect" | "circle"; depth?: number; frame?: "window";
    }
  // A big paper hand grabs the old page by a corner and pulls it away.
  | { type: "pull"; corner?: "top-right" | "top-left" };

export type Scene = {
  id?: string;
  duration: number;
  backdrop: Backdrop;
  camera?: Camera;
  actors?: Actor[]; // drawn back to front in list order (within the same depth)
  notes?: Note[];
  transition?: Transition; // how this scene arrives
};

export type Word = { text: string; at: number; end?: number };

export type Story = {
  title?: string;
  width?: number;
  height?: number;
  fps?: number;
  cast?: Character[];
  narration?: string; // audio path inside the public dir
  music?: string;
  musicVolume?: number;
  words?: Word[]; // caption timing, absolute seconds
  captions?: boolean;
  // "twos" (default): people and props move at 12 poses a second, like
  // stop-motion. "smooth": a new pose every frame.
  motion?: "twos" | "smooth";
  scenes: Scene[];
};
