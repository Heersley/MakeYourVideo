import React from 'react';
import glyphMetrics from './assets/fonts/headline_metrics.json';
import {chinese, chineseGlyph, numeric, western} from './Fonts';
import {countMotionAt} from './Game';
import {clamp, score} from './stage';
import {DigitRoll, numerals} from './Type';

const highlight = '#E2C17A';
const primary = '#F5F1E8';
const supporting = '#CCC6BB';
const readoutInk = '#C6B8A3';
const goldGlow = '0 0 20px rgba(226,193,122,0.22)';
type Beat = typeof score.beats[number];
type Weight = 400 | 700;

const trailDistances = [18, 40, 66, 96, 130];
const trailOpacity = [.46, .30, .18, .09, .04];
const blurRadii = [2, 4.2, 6.8, 9.5, 12.5];
const threadLengths = [110, 164, 134, 190];
const threadWidths = [1.2, 1.7, 1.45, 2.2];
const threadColors = [highlight, '#F2EDE4', highlight, '#F2EDE4'];
const headingDeparture = .48;
const glyphDuration = .34;
const angle = 28;
const radians = angle * Math.PI / 180;
const axisX = Math.cos(radians);
const axisY = Math.sin(radians);

const smooth = (value: number) => {
  const p = clamp(value);
  return p * p * (3 - 2 * p);
};
const plume = (u: number) => smooth((u - .04) / .18) * smooth((1 - u) / .55);
const clearAtSeam = (t: number, last: number) => smooth((last - t) / .10);

export function TextTrailDefinitions() {
  return <defs>
    {blurRadii.map((radius, i) =>
      <filter key={radius} id={`textTail${i}`} x="-68%" y="-60%" width="236%" height="220%"
        colorInterpolationFilters="sRGB">
        <feGaussianBlur stdDeviation={`${radius} ${radius * .38}`}/>
      </filter>,
    )}
    {threadLengths.map((length, i) =>
      <linearGradient key={i} id={`speedThread${i}`} gradientUnits="userSpaceOnUse" x1={-length} x2="0" y1="0" y2="0">
        <stop stopColor={threadColors[i]} stopOpacity="0"/>
        <stop offset=".54" stopColor={threadColors[i]} stopOpacity=".26"/>
        <stop offset=".96" stopColor={threadColors[i]} stopOpacity="1"/>
        <stop offset="1" stopColor={threadColors[i]} stopOpacity=".71"/>
      </linearGradient>,
    )}
  </defs>;
}

function styledLine(copy: string, row: number, closing: boolean) {
  const glyphs = copy.split(/(【[^】]+】)/).flatMap((part) => {
    const accent = part.startsWith('【');
    return Array.from(accent ? part.slice(1,-1) : part).map((char) => ({char, accent}));
  });
  const core = glyphs.some((glyph) => glyph.accent);
  const weight: Weight = core ? 700 : 400;
  const count = glyphs.filter((glyph) => glyph.char.trim()).length;
  const size = closing ? (row === 0 ? 86 : 42) : !core ? 57 : count <= 7 ? 78 : count <= 9 ? 74 : 68;
  const tracking = closing ? (row === 0 ? .05 : .28) : !core ? .06 : count <= 7 ? .05 : count <= 9 ? .04 : .03;
  const metrics = glyphMetrics[weight] as Record<string, number[]>;
  let advance = 0;
  let top = 0, bottom = 0;
  const measured = glyphs.map((glyph) => {
    const isChinese = chineseGlyph.test(glyph.char);
    const [width, ymin, ymax] = metrics[glyph.char];
    const x = advance;
    advance += (width + tracking) * size;
    top = Math.max(top, ymax * size);
    bottom = Math.max(bottom, -ymin * size);
    return {...glyph, x, family: isChinese ? chinese : western, weight: isChinese ? weight : core ? 600 : 400};
  });
  const width = advance - tracking * size;
  return {
    top, bottom, size, tracking, fill: core ? primary : supporting,
    glyphs: measured.map((glyph) => ({...glyph,x:Math.round(500 - width/2 + glyph.x)})),
  };
}

type LineLayout = ReturnType<typeof styledLine>;
type Glyph = LineLayout['glyphs'][number];

function titleStyle(layout: LineLayout) {
  return {
    fontSize:layout.size, fill:layout.fill,
    letterSpacing:`${layout.tracking}em`,
    style:{fontSynthesis:'none',fontKerning:'none',fontVariantLigatures:'none',whiteSpace:'pre'} as const,
  };
}

function GlyphPaint({glyph, layout, x, y, glow = true}: {
  glyph: Glyph; layout: LineLayout; x: number; y: number; glow?: boolean;
}) {
  return <text {...titleStyle(layout)} x={x} y={y} data-qc-text="" fontFamily={glyph.family} fontWeight={glyph.weight}
    fill={glyph.accent ? highlight : glow ? layout.fill : '#F2EDE4'}
    style={{...titleStyle(layout).style, textShadow:glyph.accent && glow ? goldGlow : undefined}}>
    {glyph.char}
  </text>;
}

function FrozenLine({layout,y}: {layout: LineLayout; y: number}) {
  return <text {...titleStyle(layout)} y={y} data-qc-text="" data-qc-role="headline"
    style={{...titleStyle(layout).style, transform:'none',filter:'none'}}>
    {layout.glyphs.map((glyph,i) =>
      <tspan key={i} x={glyph.x} fontFamily={glyph.family} fontWeight={glyph.weight}
        fill={glyph.accent ? highlight : layout.fill}
        style={glyph.accent ? {textShadow:goldGlow} : undefined}>{glyph.char}</tspan>,
    )}
  </text>;
}

function FlyingGlyph({glyph, layout, y, age, seam}: {
  glyph: Glyph; layout: LineLayout; y: number; age: number; seam: number;
}) {
  if (!glyph.char.trim()) return null;
  if (age <= 0) return <GlyphPaint glyph={glyph} layout={layout} x={glyph.x} y={y}/>;
  const u = clamp(age / glyphDuration);
  if (u >= 1 || seam === 0) return null;
  const p = u * u;
  const x = glyph.x + 185*p;
  const lift = y - 98*p;
  const alpha = u <= .35 ? 1 - .12 * (u / .35) : .88 * smooth((1 - u) / .65);
  const trail = plume(u) * seam;
  return <g data-qc-flight="">
    {trailDistances.map((length,i) => {
      const behind = length*p;
      return trail > 0 && <g key={length} data-qc-trail="" aria-hidden="true"
        transform={`translate(${x-axisX*behind} ${lift+axisY*behind}) rotate(${-angle})`}
        opacity={trailOpacity[i] * trail}>
        <g filter={`url(#textTail${i})`}>
          <g transform={`rotate(${angle})`}><GlyphPaint glyph={glyph} layout={layout} x={0} y={0} glow={false}/></g>
        </g>
      </g>;
    })}
    <g opacity={alpha*seam} transform={`translate(${x} ${lift}) scale(${1+.16*p} ${1-.08*p}) skewX(${-8*p})`}>
      <GlyphPaint glyph={glyph} layout={layout} x={0} y={0}/>
    </g>
  </g>;
}

function SpeedThreads({t, end, last, layouts, baselines}: {
  t: number; end: number; last: number; layouts: LineLayout[]; baselines: number[];
}) {
  const start = end - .44;
  const stop = Math.min(end - .04, last);
  if (t <= start || t >= stop) return null;
  const u = (t-start)/(stop-start);
  return <g aria-hidden="true">
    {threadLengths.map((length,i) => {
      const row = Math.floor(i/2);
      const glyphs = layouts[row].glyphs;
      const origin = glyphs[Math.floor(glyphs.length * (i % 2 === 0 ? .44 : .72))];
      const x = origin.x + 160*u*u + length*.43;
      const y = baselines[row] - layouts[row].size*(i%2===0 ? .60 : .24) - 85*u*u;
      const alpha = .42 * smooth(u/.26) * smooth((1-u)/.38);
      return <line key={i} data-qc-speed-thread="" x1={-length} x2="0" y1="0" y2="0" stroke={`url(#speedThread${i})`}
        strokeLinecap="round" strokeWidth={threadWidths[i]} opacity={alpha}
        transform={`translate(${x} ${y}) rotate(-${angle})`}/>;
    })}
  </g>;
}

function Headline({beat,t,last}: {beat: Beat; t: number; last: number}) {
  const closing = beat.id === 31;
  const layouts = beat.lines.map((copy,row) => styledLine(copy,row,closing));
  const [a,b] = layouts;
  const firstTop = 347 - (a.top+a.bottom+14+b.top+b.bottom)/2;
  const baselines = closing ? [890,982] : [
    Math.round(firstTop+a.top),
    Math.round(firstTop+a.top+a.bottom+14+b.top),
  ];
  const departure = beat.endSec-headingDeparture;
  const seam = clearAtSeam(t,last);
  return <>
    {!closing && <SpeedThreads t={t} end={beat.endSec} last={last} layouts={layouts} baselines={baselines}/>}
    {layouts.map((layout,row) => {
      const y = baselines[row];
      const start = departure+row*.055;
      if (closing || t <= start) return <FrozenLine key={row} layout={layout} y={y}/>;
      if (t >= last - 1e-7) return null;
      return <g key={row} data-qc-role="headline">
        {layout.glyphs.map((glyph,i) => {
          const age = t-start-(layout.glyphs.length-1-i)*.020;
          return <FlyingGlyph key={i} glyph={glyph} layout={layout} y={y} age={age} seam={seam}/>;
        })}
      </g>;
    })}
  </>;
}

function readoutWidth(text: string) {
  return Array.from(text).reduce((sum,glyph) => sum + (chineseGlyph.test(glyph) ? 32 : 19.2) + 1.92, 0);
}

function readoutLines(copy: string) {
  if (readoutWidth(copy)<=730) return [copy];
  const candidates = Array.from(copy.matchAll(/\s+·\s+|\s+⇒\s+|\s+/g), match => {
    const end = (match.index ?? 0) + match[0].length;
    const pieces = [copy.slice(0,end).trim(),copy.slice(end).trim()];
    return {pieces,diff:Math.abs(readoutWidth(pieces[0])-readoutWidth(pieces[1])),
      soft:match[0].includes('·') || match[0].includes('⇒')};
  }).filter(({pieces}) => pieces.every((line) => line && readoutWidth(line)<=730));
  candidates.sort((a,b)=>Number(b.soft)-Number(a.soft)||a.diff-b.diff);
  return candidates[0]?.pieces ?? [copy];
}

function TupleReadout({t}: {t: number}) {
  const {before,after,progress} = countMotionAt(t);
  const y=1458;
  const common = {y, fill:readoutInk, fontFamily:numeric, fontSize:32, fontWeight:400,
    textAnchor:'middle' as const, letterSpacing:'.06em', style:numerals};
  return <g data-qc-role="readout">
    <text data-qc-text="" {...common} x="388">当前局势</text>
    {['(', ',', ',', ')'].map((sign,i)=>
      <text data-qc-text="" key={i} {...common} x={486+i*49}>{sign}</text>,
    )}
    {after.map((value,i)=>
      <DigitRoll key={i} x={511+i*49} y={y} before={before[i]} after={value}
        progress={progress} size={32} color={readoutInk}/>,
    )}
  </g>;
}

function Readout({beat,t,last}: {beat: Beat; t: number; last: number}) {
  if (!beat.readout) return null;
  const closing=beat.id===31;
  const lines=readoutLines(beat.readout);
  const contents=beat.id>=5 && beat.id<=10 ? <TupleReadout t={t}/> : lines.map((copy,row)=>
    <text data-qc-text="" data-qc-role="readout" key={row} x="500"
      y={closing ? 1068 : lines.length===1 ? 1458 : 1434+40*row}
      fill={readoutInk} fontFamily={numeric} fontSize={32} fontWeight={400} textAnchor="middle"
      letterSpacing=".06em" style={{...numerals,whiteSpace:'pre',fontSynthesis:'none',transform:'none',filter:'none'}}>
      {copy}
    </text>,
  );
  const start=beat.endSec-.30;
  if (closing || t<=start) return <>{contents}</>;
  if (t>=last-1e-7) return null;
  const u=clamp((t-start)/.30);
  const p=u*u;
  const seam=clearAtSeam(t,last);
  return <g data-qc-flight="">
    {[.36,.20,.08].map((alpha,i) => {
      const lag=p*[.22,.40,.64][i];
      return <g key={i} data-qc-trail="" aria-hidden="true" opacity={alpha*plume(u)*seam}
        transform={`translate(${70*(p-lag)} ${-36*(p-lag)})`} filter={`url(#textTail${i})`}>
        {contents}
      </g>;
    })}
    <g opacity={(1-smooth(u))*seam} transform={`translate(${70*p} ${-36*p})`}>{contents}</g>
  </g>;
}

export function Narration({t,fps}: {t: number; fps: number}) {
  const beat=score.beats.find((b)=>b.startSec<=t && t<b.endSec) ?? score.beats[score.beats.length-1];
  const opacity=beat.id===1 ? 1 : clamp((t-beat.startSec)/.32);
  const last=beat.endSec-1/fps;
  return <g data-narration-beat={beat.id} opacity={opacity}>
    <Headline beat={beat} t={t} last={last}/>
    <Readout beat={beat} t={t} last={last}/>
  </g>;
}
