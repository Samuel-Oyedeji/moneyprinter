import React from "react";
import { CalculateMetadataFunction, Composition } from "remotion";
import { PaperStory, storyDuration } from "./PaperStory";
import type { Story } from "./types";
import demo from "./demo/story.json";
import { castSheet, PropSheet } from "./demo/sheets";

// PaperStory is the real composition; the story file decides its length and
// size. A workflow renders it with --props=<story.json> --public-dir=<job folder>.
const calculateMetadata: CalculateMetadataFunction<Story> = ({ props }) => {
  const fps = props.fps ?? 24;
  return {
    fps,
    width: props.width ?? 1080,
    height: props.height ?? 1920,
    durationInFrames: Math.max(1, Math.ceil(storyDuration(props) * fps)),
  };
};

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="PaperStory"
      component={PaperStory}
      defaultProps={demo as Story}
      calculateMetadata={calculateMetadata}
      width={1080}
      height={1920}
      fps={24}
      durationInFrames={240}
    />
    {/* review sheets */}
    <Composition id="CastSheet" component={PaperStory} defaultProps={castSheet} calculateMetadata={calculateMetadata} width={1080} height={1920} fps={24} durationInFrames={192} />
    <Composition id="PropSheet" component={PropSheet} width={1080} height={1920} fps={24} durationInFrames={96} />
  </>
);
