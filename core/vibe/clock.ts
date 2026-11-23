export interface Beat {
  id: number;
  startSec: number;
  endSec: number;
  readingStartSec: number;
  readingEndSec: number;
  lines: string[];
  hardCut: boolean;
}

export interface Score {
  fps: number;
  beats: readonly Beat[];
  alignClimaxSec: number;
}

type TimingProfile = {hard: {video: {fps: number; previewFps: number}}};

export function frameClock(frame: number, fps: number, score: Score, profile: TimingProfile,
                           leadSec = 0.4, fadeSec = 0.4) {
  const video = profile.hard.video;
  const rate = score.fps;
  if (rate !== video.fps || ![rate, video.previewFps].includes(fps) ||
      !Number.isSafeInteger(frame) || frame < 0 || rate % fps !== 0) {
    throw Error('Unsupported frame or timebase');
  }
  const tick = frame * (rate / fps);
  const index = score.beats.findIndex(b => tick < Math.round(b.endSec * rate));
  if (index < 0) throw Error('Frame outside score');
  const beat = score.beats[index];
  const start = Math.round(beat.startSec * rate);
  const end = Math.round(beat.endSec * rate);
  const first = index === 0;
  // Match sample_plan's half-open interval, including decimal second boundaries.
  const ceil = (sec: number) => Math.ceil(sec * rate - 1e-8);
  const readingStart = ceil(beat.readingStartSec);
  const readingEnd = ceil(beat.readingEndSec);
  const fadeStart = start + ceil(leadSec);
  const fadeEnd = fadeStart + ceil(fadeSec);
  const gapStart = ceil(beat.endSec - 0.15);
  const trailStart = gapStart - Math.round(0.66 * rate);
  if (tick < start || leadSec < 0 || fadeSec <= 0 || (!first && fadeEnd > readingStart) ||
      readingEnd > trailStart) {
    throw Error('B' + beat.id + ': reading window overlaps text entrance or exit');
  }
  const phase = !first && tick < fadeStart ? 'leadIn' : !first && tick < fadeEnd ? 'fadeIn'
    : tick < trailStart ? 'hold' : tick < gapStart ? 'trailOut' : 'gap';
  return {beat, tick, rate, phase, localFrame: tick - start, localSec: (tick - start) / rate,
    progress: (tick - start) / Math.max(1, end - start - 1),
    reading: tick >= readingStart && tick < readingEnd,
    seam: !first && !beat.hardCut && tick === start ? [start - 1, start] : null,
    climaxFrame: Math.round(score.alignClimaxSec * rate),
    fade: Math.max(0, Math.min(1, (tick - fadeStart) / (fadeEnd - fadeStart))),
    trailFrame: tick - trailStart, trailFrames: gapStart - trailStart};
}

export type FrameClock = ReturnType<typeof frameClock>;
