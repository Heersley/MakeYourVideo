import type {ReactNode, CSSProperties} from 'react';
import {stageTokens} from './tokens';

export function StageBase({tokens: t, headline, stage, labels, readout, cameraTransform}: {
  tokens: ReturnType<typeof stageTokens>; headline: ReactNode; stage: ReactNode;
  labels?: ReactNode; readout?: ReactNode; cameraTransform?: string;
}) {
  const slot = (top: number, bottom: number): CSSProperties => ({
    position: 'absolute', left: t.left, top, width: t.right - t.left, height: bottom - top,
    overflow: 'hidden',
  });
  return <div style={{position: 'absolute', inset: 0, width: t.width, height: t.height, background: t.background}}>
    <div data-vibe-slot="headline" style={slot(t.top, t.roiTop)}>{headline}</div>
    <div data-vibe-slot="stage" style={slot(t.roiTop, t.roiBottom)}>
      <div style={{position: 'absolute', inset: 0, transform: cameraTransform}}>{stage}</div>
      <div style={{position: 'absolute', inset: 0}}>{labels}</div>
    </div>
    <div data-vibe-slot="readout" style={{...slot(t.roiBottom, t.bottom),
      fontFamily: '"JetBrains Mono"', fontVariantNumeric: 'tabular-nums'}}>{readout}</div>
  </div>;
}
