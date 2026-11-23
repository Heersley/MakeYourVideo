type Lighting = 'studio_dark' | 'keynote_light';
export type StageProfile = {hard: {video: {width: number; height: number};
  visual: {safeZone: readonly number[]; roiY: readonly number[]}}};

// Design defaults version with the source snapshot. Technical bounds come from the episode.
export const stageDesign = {
  strokes: {L1: 4.5, L2: 3.5, L3: 2.5},
  backgrounds: {studio_dark: '#060709', keynote_light: '#F2F0EB'},
};

export function stageTokens(profile: StageProfile, lighting: Lighting, design = stageDesign) {
  const {video, visual} = profile.hard;
  const [left, top, right, bottom] = visual.safeZone;
  const [roiTop, roiBottom] = visual.roiY;
  if (!(0 <= left && left < right && right <= video.width &&
        0 <= top && top < roiTop && roiTop < roiBottom && roiBottom < bottom && bottom <= video.height)) {
    throw Error('Stage bounds cannot form three non-overlapping slots');
  }
  for (const key of ['L1', 'L2', 'L3'] as const) {
    if (!(design.strokes[key] >= stageDesign.strokes[key])) throw Error('Stroke below style minimum: ' + key);
  }
  return {...video, left, top, right, bottom, roiTop, roiBottom, strokes: design.strokes,
    background: design.backgrounds[lighting]};
}
