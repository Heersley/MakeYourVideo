import type {ReactNode} from 'react';
import {chinese, numeric} from './Fonts';

export const numerals = {fontVariantNumeric: 'tabular-nums', fontSynthesis: 'none'} as const;

export function standardFont(value: ReactNode) {
  if (typeof value === 'number') return numeric;
  if (typeof value === 'string' && !/\p{Script=Han}/u.test(value)) return numeric;
  return chinese;
}

export function standardWeight(value: ReactNode) {
  return standardFont(value) === numeric ? 500 : 400;
}

export function NumberSpans({value}: {value: string}) {
  return <>{value.split(/([0-9]+)/).map((part, index) =>
    index % 2 === 1 ? <tspan key={index} fontFamily={numeric} fontWeight={500}>{part}</tspan> : part,
  )}</>;
}

export function DigitRoll({x, y, before, after, progress, size = 30, color = '#F2EDE4'}: {
  x: number; y: number; before: number; after: number; progress: number; size?: number; color?: string;
}) {
  const common = {
    x: Math.round(x), fontFamily: numeric, fontSize: size, fontWeight: 500,
    textAnchor: 'middle' as const, fill: color, style: numerals,
  };
  if (before === after || progress <= 0 || progress >= 1) {
    return <text data-qc-text="" {...common} y={Math.round(y)}
      style={{...numerals, transform:'none', filter:'none'}}>{progress >= 1 ? after : before}</text>;
  }
  const height = size * 1.15;
  const width = size * (Math.max(String(before).length, String(after).length) * .68 + .12);
  const baseline = size * .90;
  const cell = {...common, x: width / 2};
  return <svg data-qc-digit-roll="" data-qc-slot-height={height} data-qc-slot-size={size} data-qc-slot-overflow="hidden"
    x={Math.round(x) - width / 2} y={Math.round(y) - baseline} width={width} height={height} style={{overflow: 'hidden'}}>
    <text {...cell} y={baseline - 14 * progress} opacity={1 - progress}>{before}</text>
    <text {...cell} y={baseline + 14 * (1 - progress)} opacity={progress}>{after}</text>
  </svg>;
}
