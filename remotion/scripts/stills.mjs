// Render a handful of stills from one bundle: node scripts/stills.mjs <outDir> <composition> <frame> [frame...]
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import path from "node:path";

const [outDir, id, ...frames] = process.argv.slice(2);
const serveUrl = await bundle({ entryPoint: path.resolve("src/index.ts") });
const composition = await selectComposition({ serveUrl, id });
for (const f of frames) {
  const t0 = Date.now();
  await renderStill({ serveUrl, composition, frame: Number(f), output: path.join(outDir, `${id}-${f}.png`) });
  console.log(`frame ${f}: ${Date.now() - t0}ms`);
}
