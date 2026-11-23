import type {CSSProperties} from 'react';
import type {FrameClock} from './clock';

const ghosts = [0.46, 0.30, 0.18, 0.09, 0.04];
const clamp = (x: number) => Math.max(0, Math.min(1, x));
const cjk = /\p{Script=Han}/u;
const latin = /[A-Za-z0-9]/;
const digit = /[0-9]/;
const unit = /[A-Za-z%‰°℃]/;

export function needsMicrospace(a: string, b: string) {
  return (cjk.test(a) && latin.test(b)) || (latin.test(a) && cjk.test(b)) ||
    (digit.test(a) && unit.test(b));
}

export function textSize(length: number, secondary: boolean) {
  return secondary ? 76 : length <= 7 ? 104 : length <= 9 ? 98 : 90;
}

export function characterState(clock: FrameClock, index: number, length: number, row = 0, rows = 1) {
  let opacity = clock.phase === 'hold' ? 1 : clock.phase === 'fadeIn' ? clock.fade : 0;
  let x = 0, y = 0, envelope = 0;
  if (clock.phase === 'trailOut') {
    const delay = ((length - 1 - index) * 0.03 + row * 0.06) * clock.rate;
    const span = Math.max(1, clock.trailFrames - ((length - 1) * 0.03 + (rows - 1) * 0.06) * clock.rate);
    const u = clamp((clock.trailFrame - delay) / span);
    x = 214 * u * u;
    y = -114 * u * u;
    opacity = 1 - clamp((u - 0.35) / 0.65);
    envelope = Math.sin(Math.PI * u);
  }
  return {opacity, transform: x || y ? `translate(${x}px, ${y}px)` : 'none',
    filter: 'none', x, y, shadows: ghosts.map(peak => peak * envelope)};
}

export function TextLifecycle({clock, lines = clock.beat.lines, x = 0, y = 0,
                              primaryLine = 0, accent = '#E2C17A', color = 'inherit'}: {
  clock: FrameClock; lines?: readonly string[]; x?: number; y?: number; primaryLine?: number;
  color?: string; accent?: string;
}) {
  return <div style={{position: 'absolute', left: Math.round(x), top: Math.round(y),
    fontFamily: '"Source Serif 4", "ChillJinshuSong"', lineHeight: 1.45, letterSpacing: '0.06em', color}}>
    {lines.map((line, row) => {
      const glyphs = Array.from(line.replace(/[【】]/g, ''));
      const secondary = row !== primaryLine;
      let emphasized = false;
      let index = 0;
      return <div key={row} data-vibe-static-text="true" data-beat-id={clock.beat.id}
        data-holding={clock.reading} style={{width: 'max-content', whiteSpace: 'pre',
          fontWeight: secondary ? 400 : 700, fontSize: textSize(glyphs.length, secondary)}}>
        {Array.from(line).map(char => {
          if (char === '【' || char === '】') {emphasized = char === '【'; return null;}
          const i = index++;
          const state = characterState(clock, i, glyphs.length, row, lines.length);
          const spacing = i && needsMicrospace(glyphs[i-1], char) ? '0.15em' : undefined;
          const style: CSSProperties = {display: 'inline-block', position: 'relative',
            marginLeft: spacing, color: emphasized ? accent : undefined};
          return <span key={i} style={style}>
            <span style={{display: 'inline-block', opacity: state.opacity,
              transform: state.transform, filter: state.filter}}>{char}</span>
            {state.shadows.map((opacity, j) => opacity > 0 && <span key={j} aria-hidden style={{
              position: 'absolute', inset: 0, opacity, filter: `blur(${j+1}px)`,
              transform: `translate(${state.x - (j+1)*6}px,${state.y + (j+1)*3}px)`,
            }}>{char}</span>)}
          </span>;
        })}
      </div>;
    })}
  </div>;
}
