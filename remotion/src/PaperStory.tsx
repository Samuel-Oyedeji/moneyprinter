import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import type { Story } from "./types";
import { Captions } from "./components/Captions";
import { Grain } from "./components/Grain";
import { SceneView } from "./components/SceneView";

export const TEAR_SECONDS = 0.7;
export const CAPTION_INK = "#2b3a8f";
export const CAPTION_ACCENT = "#d1495b";

export const storyDuration = (s: Story) => s.scenes.reduce((sum, sc) => sum + sc.duration, 0);

export const PaperStory: React.FC<Story> = (story) => {
  const { fps } = useVideoConfig();
  const half = TEAR_SECONDS / 2;
  const tears = story.scenes.map((s, i) => i > 0 && (s.transition ?? "tear") === "tear");

  let start = 0;
  const seqs = story.scenes.map((scene, i) => {
    const lead = tears[i] ? half : 0; // start early so the tear can reveal it
    const trail = tears[i + 1] ? half : 0; // stay under the next scene's tear
    const from = Math.round((start - lead) * fps);
    const frames = Math.round((scene.duration + lead + trail) * fps);
    start += scene.duration;
    return (
      <Sequence key={i} from={from} durationInFrames={frames} name={scene.id ?? `scene ${i + 1}`}>
        <SceneView scene={scene} cast={story.cast ?? []} index={i} lead={lead} wipe={tears[i] ? Math.round(TEAR_SECONDS * fps) : 0} />
      </Sequence>
    );
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#1c1f5e" }}>
      {seqs}
      {story.captions !== false && story.words?.length ? <Captions words={story.words} ink={CAPTION_INK} accent={CAPTION_ACCENT} /> : null}
      <Grain />
      {story.narration ? <Audio src={staticFile(story.narration)} /> : null}
      {story.music ? <Audio src={staticFile(story.music)} volume={story.musicVolume ?? 0.12} /> : null}
    </AbsoluteFill>
  );
};
