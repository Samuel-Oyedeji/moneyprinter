// Render one story to MP4 for the Animation pipeline.
//
//   node scripts/render.mjs --props story.json --public-dir <job>/public --out final.mp4
//        [--scale 1] [--concurrency N]
//
// Bundles once with the job's public folder (it holds only the narration),
// renders the PaperStory composition, and prints one JSON line per progress
// step so the Python side can show a live percentage. The bundle goes in a
// sibling folder — never inside the public dir, which the bundler copies —
// and is removed afterwards.
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, arg, i, all) => (arg.startsWith("--") ? [...pairs, [arg.slice(2), all[i + 1]]] : pairs), []),
);
const say = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const inputProps = JSON.parse(fs.readFileSync(args.props, "utf8"));
const publicDir = path.resolve(args["public-dir"]);
const outDir = path.join(path.dirname(publicDir), ".bundle");
if (path.resolve(outDir).startsWith(publicDir + path.sep)) throw new Error("bundle dir must not be inside the public dir");

try {
  say({ stage: "bundling", progress: 0 });
  const serveUrl = await bundle({ entryPoint: path.join(root, "src/index.ts"), publicDir, outDir });
  const composition = await selectComposition({ serveUrl, id: "PaperStory", inputProps });
  let last = -1;
  await renderMedia({
    composition,
    serveUrl,
    codec: "h264",
    outputLocation: path.resolve(args.out),
    inputProps,
    scale: args.scale ? Number(args.scale) : 1,
    concurrency: args.concurrency ? Number(args.concurrency) : null,
    onProgress: ({ progress }) => {
      const pct = Math.floor(progress * 100);
      if (pct !== last) {
        last = pct;
        say({ stage: "rendering", progress });
      }
    },
  });
  say({ stage: "done", progress: 1, frames: composition.durationInFrames });
} catch (err) {
  say({ stage: "error", error: String(err?.stack || err) });
  process.exitCode = 1;
} finally {
  fs.rmSync(outDir, { recursive: true, force: true });
}
