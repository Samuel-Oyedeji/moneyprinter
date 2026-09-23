import { continueRender, delayRender } from "remotion";
import "@fontsource/patrick-hand";
import "@fontsource/fredoka/600.css";
import "@fontsource/fredoka/700.css";

export const HAND_FONT = "'Patrick Hand', 'Comic Sans MS', cursive"; // captions, labels
export const TITLE_FONT = "'Fredoka', 'Arial Rounded MT Bold', sans-serif"; // titles, stamps

// Canvas text draws with whatever font is ready, so hold the render until
// both faces have loaded. One shared promise for every canvas on the page.
let ready: Promise<void> | null = null;

export function fontsReady(): Promise<void> {
  if (!ready) {
    ready = Promise.all([
      document.fonts.load(`48px 'Patrick Hand'`),
      document.fonts.load(`600 48px 'Fredoka'`),
      document.fonts.load(`700 48px 'Fredoka'`),
    ]).then(() => undefined);
  }
  return ready;
}

export function holdForFonts() {
  const handle = delayRender("fonts");
  fontsReady().then(() => continueRender(handle));
  return handle;
}
