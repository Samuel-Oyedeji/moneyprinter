import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import type { Scene, Story } from "./types";
import { isPerson } from "./types";
import { setMotion } from "./kit/motion";
import { TRANSITION_SECONDS, transitionSpec } from "./components/Transitions";
import type { Spec } from "./components/Transitions";
import { Captions } from "./components/Captions";
import { Grain } from "./components/Grain";
import { SceneView } from "./components/SceneView";

export const CAPTION_INK = "#2b3a8f";
export const CAPTION_ACCENT = "#d1495b";

export const storyDuration = (s: Story) => s.scenes.reduce((sum, sc) => sum + sc.duration, 0);

// A "hand" transition starts with the person raising their hand in the
// scene before, so the palm that fills the lens is clearly theirs.
function withTransitionActing(scenes: Scene[], specs: Spec[]): Scene[] {
  return scenes.map((scene, i) => {
    const next = specs[i + 1];
    if (next?.type !== "hand") return scene;
    const people = (scene.actors ?? []).filter(isPerson);
    const who = (people.find((p) => p.who === next.who) ?? people[0])?.who;
    if (!who) return scene;
    const raise = { do: "wave" as const, at: Math.max(0, scene.duration - TRANSITION_SECONDS.hand / 2 - 0.35), dur: 1.4 };
    return {
      ...scene,
      actors: scene.actors?.map((a) => (isPerson(a) && a.who === who ? { ...a, actions: [...(a.actions ?? []), raise] } : a)),
    };
  });
}

export const PaperStory: React.FC<Story> = (story) => {
  const { fps, width, height } = useVideoConfig();
  setMotion(story.motion);
  const specs: Spec[] = story.scenes.map((s, i) => (i === 0 ? { type: "cut" } : transitionSpec(s.transition, story.scenes[i - 1], width, height)));
  const secs = specs.map((s) => TRANSITION_SECONDS[s.type]);
  const scenes = withTransitionActing(story.scenes, specs);

  let start = 0;
  const seqs = scenes.map((scene, i) => {
    const lead = secs[i] / 2; // start early: the way in overlaps the previous scene
    const trail = i + 1 < scenes.length ? secs[i + 1] / 2 : 0; // stay on during the next one's way in
    const from = Math.round((start - lead) * fps);
    const frames = Math.round((scene.duration + lead + trail) * fps);
    start += scene.duration;
    const enter = secs[i] > 0 ? { spec: specs[i], frames: Math.round(secs[i] * fps), prev: scenes[i - 1] } : null;
    const exit = trail > 0 ? { spec: specs[i + 1], frames: Math.round(secs[i + 1] * fps), start: Math.round((lead + scene.duration - trail) * fps) } : null;
    return (
      <Sequence key={i} from={from} durationInFrames={frames} name={scene.id ?? `scene ${i + 1}`}>
        <SceneView scene={scene} cast={story.cast ?? []} index={i} lead={lead} enter={enter} exit={exit} />
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
