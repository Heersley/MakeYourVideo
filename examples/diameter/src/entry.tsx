import {Composition, registerRoot, useCurrentFrame, useVideoConfig} from 'remotion';
import scoreFile from '../beats.json';
import manifest from './manifest.json';
import {Diagram} from './Diagram';
import {frameClock, type Score} from './vendor/vibe/clock';
import {Fonts} from './vendor/vibe/Fonts';
import {StageBase} from './vendor/vibe/StageBase';
import {TextLifecycle} from './vendor/vibe/TextLifecycle';
import {stageTokens, type StageProfile} from './vendor/vibe/tokens';

type Profile = StageProfile & {hard: {video: {fps: number; previewFps: number}}};
type EpisodeScore = Score & {lighting: 'studio_dark' | 'keynote_light'};
type Props = {profile?: Profile; score?: EpisodeScore};

function Episode({profile, score}: Props) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (!profile || !score) throw Error('Run this entry through tools/episode.py');
  const clock = frameClock(frame, fps, score, profile);
  return <Fonts folder="fonts">
    <StageBase tokens={stageTokens(profile, score.lighting)}
      headline={<TextLifecycle clock={clock} x={28} y={95} color="#f2ede4"/>}
      stage={<Diagram progress={clock.beat.id - 1 + clock.progress}/>}
      readout={null}/>
  </Fonts>;
}

function Root() {
  const {totalSec, fps} = scoreFile;
  return <>
    <Composition id="Preview" component={Episode} width={1440} height={2560} fps={30}
      durationInFrames={manifest.previewFrames}/>
    <Composition id="Cinema" component={Episode} width={1440} height={2560} fps={fps}
      durationInFrames={totalSec * fps}/>
  </>;
}

registerRoot(Root);
