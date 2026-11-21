import React from 'react';
import {Easing} from 'remotion';
import beats from '../beats.json';
import {NumberSpans, standardFont, standardWeight} from './Type';

export const score = beats;
export const gold = '#C9A96A';
export const ink = '#F2EDE4';
export const dim = '#5C6370';
export const rust = '#B85D4B';
export const silver = '#8B94A3';

export const clamp = (v: number) => Math.max(0, Math.min(1, v));
const cinema = Easing.bezier(0.16, 1, 0.3, 1);
const camera = Easing.bezier(0.65, 0, 0.35, 1);
export const ramp = (t: number, a: number, b: number) => cinema(clamp((t - a) / (b - a)));
export const slide = (t: number, a: number, b: number) => camera(clamp((t - a) / (b - a)));
export const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
export const pulse = (t: number, a: number, b: number, c: number) =>
  slide(t, a, b) * (1 - slide(t, b, c));

const soft = score.beats.filter(b => b.startSec > 0 && !b.hardCut);
export function clock(frame: number, fps: number) {
  // Reuse the terminal state for the one boundary frame in a continuous shot.
  const isSeam = soft.some(b => Math.round(b.startSec * fps) === frame);
  return (frame - Number(isSeam)) / fps;
}

export const line = (x: number, y: number, X: number, Y: number, c = gold, w = 2, o = 1) =>
  <line x1={x} y1={y} x2={X} y2={Y} stroke={c} strokeWidth={w} opacity={o} strokeLinecap="round"/>;
export const path = (d: string, c = gold, o = 1, w = 2, more: React.SVGProps<SVGPathElement> = {}) =>
  <path d={d} fill="none" stroke={c} opacity={o} strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" {...more}/>;
export const label = (
  x: number, y: number, content: React.ReactNode, size = 25, c = ink,
  anchor: 'start' | 'middle' | 'end' = 'middle',
) => (
  <text data-qc-text="" x={Math.round(x)} y={Math.round(y)} fontSize={size} fill={c} textAnchor={anchor}
    fontFamily={standardFont(content)} fontWeight={standardWeight(content)}
    style={{fontVariantNumeric: 'tabular-nums', fontSynthesis:'none', transform: 'none', filter: 'none'}}>
    {typeof content === 'string' ? <NumberSpans value={content}/> : content}
  </text>
);
export const core = (x: number, y: number, r = 6, o = 1) => (
  <g opacity={o}>
    <circle cx={x} cy={y} r={5.1 * r} fill="url(#nimHalo)" opacity=".26"/>
    <circle cx={x} cy={y} r={r} fill="url(#nimPearl)"/>
    <circle cx={x - r * .23} cy={y - r * .27} r={r * .33} fill="#FFF6DF"/>
  </g>
);

export const OpticalDefs = () => <defs>
  <radialGradient id="nimHalo">
    <stop stopColor="#F0D594"/>
    <stop offset=".28" stopColor="#D4B473" stopOpacity=".72"/>
    <stop offset=".66" stopColor={gold} stopOpacity=".23"/>
    <stop offset="1" stopColor={gold} stopOpacity="0"/>
  </radialGradient>
  <radialGradient id="nimPearl" cx=".34" cy=".26">
    <stop stopColor="#FFF6DF"/>
    <stop offset="1" stopColor="#F0D594"/>
  </radialGradient>
</defs>;
