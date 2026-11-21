import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {BrassGamePlinth, FacetedStone, GameDefs, heapX, preloadStones, stoneMorph, stoneY, StoneCloseup} from './Game';
import {Epilogue, ZeroTray} from './Epilogue';
import {FontLayer} from './Fonts';
import {Narration, TextTrailDefinitions} from './Narration';
import {BinaryWeightMatrix, ProofStage, weightColumns, weightRows, weightWidths} from './Proof';
import {clock, gold, lerp, line, OpticalDefs, ramp, slide} from './stage';

const backdrop = 'radial-gradient(circle at 50% 54%, rgba(201,169,106,0.068) 0%, rgba(201,169,106,0.018) 38%, rgba(6,7,9,0) 70%)';
const closingHeaps = [1, 2, 3] as const;
const rebuiltHeaps = [1, 4, 6] as const;

function makeStaticGrain() {
  let seed = 190110;
  const sample = () => {
    seed = Math.imul(seed, 1664525) + 1013904223 | 0;
    return (seed >>> 0) / 4294967296;
  };
  const dots = Array.from({length: 1150}, () => {
    const x = Math.floor(sample() * 180), y = Math.floor(sample() * 180);
    return `<rect x="${x}" y="${y}" width="1" height="1" fill="${sample() > .54 ? '#d6c7a9' : '#020204'}" />`;
  });
  return `url("data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180">${dots.join('')}</svg>`)}")`;
}
const grain = makeStaticGrain();

function BinaryHandoff({t}: {t: number}) {
  const morph = Array.from({length:3}, (_,i)=>ramp(t, 59.0 + i*.6, 61.1 + i*.6));
  const reveal = ramp(t,59.48,62.55);
  return <>
    <BinaryWeightMatrix heaps={rebuiltHeaps} t={t} opacity={reveal} showResult={false}
      showHeaders phase={reveal} stoneMorph={morph}/>
    {[[2],[0],[0,1]].map((cols, row) => cols.map((col, i) => {
      const p = morph[row], alpha = ramp(t,58.75,59.08) * (1-slide(p,.84,1));
      return <React.Fragment key={row*3+col}>
        {stoneMorph(heapX[row],stoneY(i),weightColumns[col],weightRows[row],weightWidths[col],p,alpha)}
      </React.Fragment>;
    }))}
  </>;
}

function Stage({t, fps}: {t: number; fps: number}) {
  const restored = t >= 53.35;
  const live = 1 - slide(t,53.0,53.35);
  const rebuilt = ramp(t,53.35,54.75) * (1-slide(t,58.58,59.26));
  const scan = ramp(t,54.2,56.0);
  const scanOpacity = ramp(t,54.2,54.5) * (1-slide(t,55.95,56.3));
  const lateBoard = ramp(t,162.44,163.12) * (1-slide(t,174.4,174.75));
  const closingStones = 1-slide(t,173.94,174.37);
  if(t < 58.75) return <>
    {live > 0 && <BrassGamePlinth t={t} fps={fps} opacity={live}/>}
    {restored && <BrassGamePlinth t={t} fps={fps} heaps={rebuiltHeaps} opacity={rebuilt}/>}
    {scanOpacity > 0 && <g opacity={scanOpacity}>
      <ellipse cx="500" cy={lerp(808,1123,scan)} rx="340" ry="16" fill="url(#nimRailReflection)" opacity=".44"/>
      {line(194,lerp(808,1123,scan),806,lerp(808,1123,scan),gold,1.7,.64)}
    </g>}
  </>;
  if(t < 64) return <>
    {rebuilt > 0 && <BrassGamePlinth t={t} fps={fps} heaps={rebuiltHeaps} opacity={rebuilt}/>}
    <BinaryHandoff t={t}/>
  </>;
  if(t < 142) return <ProofStage t={t}/>;
  return <>
    <Epilogue t={t}/>
    {lateBoard > 0 && <BrassGamePlinth t={t} fps={fps} heaps={closingHeaps} opacity={lateBoard} stonesOpacity={0}/>}
    <ZeroTray t={t}/>
    {t >= 162.55 && closingStones > 0 &&
      <g opacity={closingStones}>
        {closingHeaps.flatMap((n,i)=>Array.from({length:n},(_,j)=>
          <FacetedStone key={i*3+j} x={heapX[i]} y={stoneY(j)} variant={(j+i*2)%4} t={t}/>,
        ))}
      </g>}
  </>;
}

export function Frame({frame, fps}: {frame: number; fps: number}) {
  const t = clock(frame,fps);
  return <AbsoluteFill style={{backgroundColor:'#060709',backgroundImage:backdrop}}>
    <FontLayer preload={preloadStones}/>
    <AbsoluteFill style={{backgroundImage:grain,opacity:.035}}/>
    <svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920"
      style={{position:'absolute',inset:0,overflow:'hidden'}}>
      <OpticalDefs/>
      <GameDefs/>
      <Stage t={t} fps={fps}/>
    </svg>
    <svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920"
      style={{position:'absolute',inset:0,pointerEvents:'none'}}>
      <TextTrailDefinitions/>
      <Narration t={t} fps={fps}/>
    </svg>
  </AbsoluteFill>;
}

export function Nim() {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return <Frame frame={frame} fps={fps}/>;
}

export function NimStoneCloseup() {
  return <AbsoluteFill style={{backgroundColor:'#060709',backgroundImage:backdrop}}>
    <FontLayer preload={preloadStones}/>
    <svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920">
      <OpticalDefs/>
      <GameDefs/>
      <StoneCloseup/>
    </svg>
  </AbsoluteFill>;
}
