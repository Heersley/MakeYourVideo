import React from 'react';
import {staticFile} from 'remotion';
import geometry from './assets/stone_geometry.json';
import {countAt, countMotionAt, flight, flightDuration, gameMovesAt, heapX, laidPosition,
  lowerRailY, type Move, stoneY, upperRailY} from './Motion';
import {core, gold, ink, label, lerp, line, path, ramp, score, silver, slide} from './stage';
import {DigitRoll} from './Type';

export {countAt, countMotionAt, heapX, stoneY};

const roman = ['I', 'II', 'III'];
const softGold = '#F5DBA0';
const softSilver = '#9AA6B8';
const cue = (index: number) => score.effects[index - 1].timeSec;
const boardTrack = 'M221 751H859L958 1153L929 1194H151L122 1153Z';
const innerTrack = 'M231 760H849L942 1151L921 1186H159L138 1151Z';
const previewRailLength = 2475;
const spriteScale = 151 / geometry.width;
const spriteWidth = geometry.width * spriteScale;
const spriteHeight = geometry.height * spriteScale;
const spriteX = -geometry.anchor[0] * spriteScale;
const spriteY = -geometry.anchor[1] * spriteScale;
const sprites = geometry.variants.map((_, index) => staticFile(`stone_v${index}.png`));

export async function preloadStones() {
  await Promise.all(sprites.map(async (src) => {
    const image = new Image();
    image.src = src;
    await image.decode();
  }));
}

export const GameDefs = () => <defs>
  <linearGradient id="nimTableSurface" x1=".27" x2=".75" y1="0" y2="1">
    <stop stopColor="#0B0A08"/><stop offset="1" stopColor="#12100C"/>
  </linearGradient>
  <linearGradient id="nimFascia" x1="0" x2="0" y1="0" y2="1">
    <stop stopColor="#4C3A2A"/><stop offset=".16" stopColor="#685137"/>
    <stop offset=".52" stopColor="#4B3928"/><stop offset=".84" stopColor="#423225"/><stop offset="1" stopColor="#31271D"/>
  </linearGradient>
  <linearGradient id="nimBrightBevel" x1="0" x2="0" y1="0" y2="1">
    <stop stopColor="#72573A"/><stop offset=".41" stopColor="#89704F"/>
    <stop offset=".67" stopColor="#55402C"/><stop offset="1" stopColor="#372A1C"/>
  </linearGradient>
  <linearGradient id="nimRailRim" x1="0" x2="1" y1="0" y2="0">
    <stop stopColor="#5F4F3C"/><stop offset=".22" stopColor="#8B6D4C"/>
    <stop offset=".45" stopColor="#2B2117"/><stop offset=".62" stopColor="#605035"/><stop offset=".87" stopColor="#8B6D4C"/><stop offset="1" stopColor="#524432"/>
  </linearGradient>
  <radialGradient id="nimRailReflection">
    <stop stopColor="#F5DBA0" stopOpacity=".81"/><stop offset=".45" stopColor="#CBAE73" stopOpacity=".30"/>
    <stop offset="1" stopColor="#765331" stopOpacity="0"/>
  </radialGradient>
  <radialGradient id="nimFacetReflection">
    <stop stopColor="#DCC091" stopOpacity=".88"/>
    <stop offset=".30" stopColor="#CAAB7A" stopOpacity=".61"/>
    <stop offset=".63" stopColor="#B68F62" stopOpacity=".36"/>
    <stop offset="1" stopColor="#91704E" stopOpacity="0"/>
  </radialGradient>
  <radialGradient id="nimStoneSelectWarm">
    <stop stopColor={softGold} stopOpacity=".88"/><stop offset="1" stopColor={gold} stopOpacity="0"/>
  </radialGradient>
  <radialGradient id="nimStoneSelectCool">
    <stop stopColor={softSilver} stopOpacity=".75"/><stop offset="1" stopColor={silver} stopOpacity="0"/>
  </radialGradient>
  <linearGradient id="nimMirrorFade" x1="0" x2="0" y1="0" y2="1">
    <stop stopColor="white"/><stop offset="1" stopColor="black"/>
  </linearGradient>
  <radialGradient id="nimWinField">
    <stop stopColor="#2B2218"/><stop offset=".77" stopColor="#19140F"/><stop offset="1" stopColor="#251D13"/>
  </radialGradient>
  <clipPath id="nimBevelLight">
    <path d="M218 724H862L984 1158V1264L948 1304H132L96 1264V1158ZM221 751H859L958 1153L929 1194H151L122 1153Z" fillRule="evenodd" clipRule="evenodd"/>
  </clipPath>
  <clipPath id="nimLiveProjection">
    <rect x="0" y="0" width="1080" height="1145"/>
  </clipPath>
</defs>;

function ObsidianSprite({variant}: {variant: number}) {
  return <image href={sprites[variant]} x={spriteX} y={spriteY} width={spriteWidth} height={spriteHeight}/>;
}

const stonePoint = ([x, y]: number[]) => [x * spriteScale + spriteX, y * spriteScale + spriteY];
const contact = (variant: number) => stonePoint(geometry.variants[variant].contact)[1];

function StoneProjection({x, y, variant, size, lift, reflect, opacity, live = false}: {
  x: number; y: number; variant: number; size: number; lift: number; reflect: boolean; opacity: number; live?: boolean;
}) {
  const ground = y + contact(variant) * size;
  const spread = 1 + lift * .008;
  const falloff = Math.exp(-lift / 38) * opacity;
  return <g opacity={falloff} clipPath={live ? 'url(#nimLiveProjection)' : undefined}>
    {reflect && <svg x={x - spriteWidth * size / 2 - 4} y={ground} width={spriteWidth * size + 8} height={26} overflow="hidden">
      <mask id={`nimReflection-${variant}-${Math.round(x)}-${Math.round(y)}`} maskUnits="userSpaceOnUse"
        x={0} y={0} width={spriteWidth * size + 8} height={26}>
        <rect width={spriteWidth * size + 8} height="26" fill="url(#nimMirrorFade)"/>
      </mask>
      <g mask={`url(#nimReflection-${variant}-${Math.round(x)}-${Math.round(y)})`} opacity=".13" style={{filter: 'blur(1.5px)'}}>
        <g transform={`translate(${spriteWidth * size / 2 + 4} ${contact(variant) * size * .52}) scale(${size} ${-size * .52})`}>
          <ObsidianSprite variant={variant}/>
        </g>
      </g>
    </svg>}
    <ellipse cx={x} cy={ground - 3 * size} rx={52 * size * spread} ry={13 * size * spread} fill="black" opacity=".46"
      style={{filter: `blur(${12 + lift * .22}px)`}}/>
    <ellipse cx={x} cy={ground - 3 * size} rx={44 * size * spread} ry={6 * size * spread} fill="black" opacity=".82"
      style={{filter: `blur(${3 + lift * .22}px)`}}/>
  </g>;
}

type StoneProps = {
  x: number; y: number; opacity?: number; tint?: string; selected?: number; scale?: number; variant?: number;
  t?: number; base?: boolean; shadow?: boolean; lift?: number; groundX?: number; groundY?: number; liveProjection?: boolean;
};

export function FacetedStone({x, y, opacity = 1, tint = gold, selected = 0, scale = 1, variant = 0,
  t = 0, base = false, shadow = true, lift = 0, groundX = x, groundY = y, liveProjection = false}: StoneProps) {
  const model = geometry.variants[variant];
  const outer = model.lipOutline.map(stonePoint);
  const rim = outer.map(([u, v]) => `${u},${v}`).join(' ');
  const shine = .17 + .05 * Math.sin(t * 2 * Math.PI / 1.8 + variant * .48);
  const cool = tint === silver || tint === softSilver;
  return <>
    {shadow && <StoneProjection x={groundX} y={groundY} variant={variant} size={scale} lift={lift} reflect={base}
      opacity={opacity} live={liveProjection}/>}
    <g opacity={opacity} transform={`translate(${x} ${y}) scale(${scale})`}>
      {selected > 0 && <ellipse cy={contact(variant) - 9} rx={84} ry={25}
        fill={cool ? 'url(#nimStoneSelectCool)' : 'url(#nimStoneSelectWarm)'} opacity={(cool ? .18 : .22) * selected}/>}
      <ObsidianSprite variant={variant}/>
      {model.litPaths.map((edge, index) => {
        const [start, stop] = edge.map(stonePoint);
        return <React.Fragment key={index}>{line(start[0], start[1], stop[0], stop[1], softGold, 1.8, shine)}</React.Fragment>;
      })}
      {selected > 0 && <polygon points={rim} fill="none" stroke={cool ? softSilver : softGold}
        strokeWidth={1.5} opacity={selected} strokeLinejoin="round"/>}
    </g>
  </>;
}

export function stoneMorph(x: number, y: number, X: number, Y: number, width: number, progress: number, opacity = 1) {
  const [w, h] = [width / 2, 31];
  const finish = [[w,-23],[w-7,h],[-w+7,h],[-w,23],[-w,-24],[-w+7,-32],[w-7,-32],[w,-24]];
  const model = geometry.variants[0].chamferRing.map(stonePoint);
  const points = model.map(([px, py], i) => `${lerp(px, finish[i][0], progress)},${lerp(py, finish[i][1], progress)}`).join(' ');
  const becomeBrick = ramp(progress, .10, .72);
  return <g opacity={opacity} transform={`translate(${lerp(x, X, progress)} ${lerp(y, Y, progress)})`}>
    <g opacity={1 - becomeBrick}><ObsidianSprite variant={0}/></g>
    <polygon points={points} fill={progress > .35 ? '#302317' : '#13131A'} stroke={gold} strokeWidth="1.4" opacity={becomeBrick}/>
    {path(`M${lerp(-45,-w+4,progress)} ${lerp(-12,0,progress)}H${lerp(37,w-4,progress)}`, softGold, becomeBrick * .8, 1.1)}
  </g>;
}

const jawDistance = (grip: number, scale: number) => (70 + 22 * (1 - grip)) * scale;

export function ExtractionCaliper({x, firstY, lastY, grip, color, scale = 1, rulesDemo = false}: {
  x: number; firstY: number; lastY: number; grip: number; color: string; scale?: number; rulesDemo?: boolean;
}) {
  const upper = firstY - 49 * scale;
  const lower = Math.max(upper + 65 * scale, lerp(firstY, lastY, grip) + 38 * scale);
  const distance = jawDistance(grip, scale);
  return <g transform={`translate(${x} 0)`}>
    {[-1, 1].map(side => <g key={side} transform={`scale(${side} 1)`}
      data-b03-callout={rulesDemo && side < 0 ? 'left-jaw' : undefined}
      data-b03-jaw-left={rulesDemo && side < 0 ? x - distance - 8 * scale : undefined}>
      {path(`M${distance - 14 * scale} ${upper}H${distance}V${lower}h${-11 * scale}`, color, .24, 5 * scale)}
      {path(`M${distance - 14 * scale} ${upper}H${distance}V${lower}h${-11 * scale}`, color, .89, Math.max(1, 1.5 * scale))}
      {Array.from({length: 4}, (_, tick) => <React.Fragment key={tick}>
        {line(distance, upper + (tick + 1) * 7 * scale, distance + (tick % 3 === 0 ? 8 : 4) * scale,
          upper + (tick + 1) * 7 * scale, color, .82, .71)}
      </React.Fragment>)}
      <circle cx={distance} cy={upper} r={5 * scale} fill="none" stroke={color} strokeOpacity=".35"/>
      <circle cx={distance} cy={upper} r={1.65 * scale} fill={color} opacity=".84"/>
    </g>)}
  </g>;
}

function TableGeometry({t}: {t: number}) {
  const phase = t * Math.PI * 2 / 1.54;
  const light = Math.sin(phase);
  const cross = Math.cos(phase);
  return <g>
    <path d="M218 724H862L984 1158V1264L948 1304H132L96 1264V1158Z" fill="url(#nimFascia)" stroke="#332B21" strokeWidth="1"/>
    <path d="M218 724H862L984 1158L966 1182L932 1211H148L114 1182L96 1158Z" fill="url(#nimBrightBevel)" stroke="#39291B" strokeWidth="1"/>
    <path d="M96 1191L151 1223H929L984 1191V1210L929 1240H151L96 1210Z" fill="url(#nimRailRim)" opacity=".9"/>
    <path d="M97 1257L143 1288H937L983 1257L948 1304H132Z" fill="url(#nimBrightBevel)" opacity=".86"/>
    <g clipPath="url(#nimBevelLight)">
      <ellipse cx={540 + 248 * light} cy={1238} rx={353} ry={78} fill="url(#nimFacetReflection)" opacity={.43}/>
      <ellipse cx={540 - 244 * cross} cy={1278} rx={333} ry={71} fill="url(#nimFacetReflection)" opacity={.39}/>
      <ellipse cx={540 - 202 * light} cy={738} rx={276} ry={43} fill="url(#nimFacetReflection)" opacity={.28}/>
    </g>
    <path d={boardTrack} fill="url(#nimTableSurface)" stroke={gold} strokeWidth="1.2" strokeOpacity=".52"/>
    {path(innerTrack, gold, .22, .7)}
    {path(boardTrack, softGold, .36, 2.35, {
      pathLength: previewRailLength, strokeDasharray: `84 ${previewRailLength - 84}`, strokeDashoffset: -t * 81,
    })}
    {path('M403 771L383 1139 M597 771L617 1139', gold, .18, .8, {strokeDasharray: '2 7'})}
    {path('M172 1147H906 M161 1199H919 M152 1241H928', gold, .34, 1)}
    {Array.from({length: 43}, (_, i) => <React.Fragment key={i}>
      {line(154 + i * 18, 1200, 154 + i * 18, 1200 + (i % 5 === 0 ? 11 : 4), gold, .65, i % 5 === 0 ? .47 : .23)}
    </React.Fragment>)}
  </g>;
}

function CollectingRail({y, player, color}: {y: number; player: 'first' | 'second'; color: string}) {
  return <g data-rail-player={player} data-rail-y={y}>
    {path(`M131 ${y + 4}l18 -8h198l13 8h280l13 -8h217l18 8 M151 ${y + 6}H343 M658 ${y + 6}H868`, color, .53, 1)}
    {Array.from({length: 12}, (_, i) => <React.Fragment key={i}>
      {line(155 + i * 17, y + 4, 155 + i * 17, y + (i % 4 ? 8 : 12), color, .58, .44)}
      {line(665 + i * 17, y + 4, 665 + i * 17, y + (i % 4 ? 8 : 12), color, .58, .44)}
    </React.Fragment>)}
  </g>;
}

function FlyingStone({move, index, t, fps}: {move: Move; index: number; t: number; fps: number}) {
  const pos = flight(move, index, t);
  const variant = (index + (move.heap - 1) * 2) % 4;
  const tint = move.player === 'first' ? softGold : softSilver;
  const age = t - move.timeSec;
  const trail = ramp(age, .17, .31) * (1 - slide(age, .60, .78));
  const points = Array.from({length: 8}, (_, i) => flight(move, index, t - (7 - i) / fps));
  return <g data-pick-frame={move.timeSec} data-pick-player={move.player} data-pick-heap={move.heap}
    data-pick-index={index} data-pick-x={pos.x.toFixed(3)} data-pick-y={pos.y.toFixed(3)}
    data-pick-target-x={pos.target.x} data-pick-target-y={pos.target.y}
    data-route-actor={move.player} data-route-x={pos.x} data-route-y={pos.y}>
    <StoneProjection x={pos.origin.x} y={pos.origin.y} variant={variant} size={1} lift={pos.lift}
      reflect={index === 0} opacity={pos.opacity} live={true}/>
    {index === move.before[move.heap - 1] - 1 && trail > 0 &&
      path(points.map((point, i) => `${i === 0 ? 'M' : 'L'}${point.x} ${point.y}`).join(' '), tint, .47 * trail, 1.45)}
    {[{frames: 4, opacity: .08, blur: 2}, {frames: 2, opacity: .20, blur: .9}].map(echo => {
      if (trail === 0) return null;
      const lag = flight(move, index, t - echo.frames / fps);
      return <g key={echo.frames} style={{filter: `blur(${echo.blur}px)`}}>
        <FacetedStone x={lag.x} y={lag.y} variant={variant} scale={lag.scale} opacity={trail * echo.opacity} shadow={false} t={t}/>
      </g>;
    })}
    <FacetedStone x={pos.x} y={pos.y} variant={variant} scale={pos.scale} opacity={pos.opacity}
      selected={pos.grip} tint={tint} shadow={false} t={t}/>
  </g>;
}

function FlightCaliper({move, t}: {move: Move; t: number}) {
  const row = move.heap - 1;
  const high = flight(move, move.before[row] - 1, t);
  const low = flight(move, move.after[row], t);
  const color = move.player === 'first' ? softGold : softSilver;
  return <g opacity={ramp(t, move.timeSec, move.timeSec + .105) * high.opacity}>
    <ExtractionCaliper x={lerp(high.x, low.x, .5)} firstY={Math.min(high.y, low.y)} lastY={Math.max(high.y, low.y)}
      grip={high.grip} scale={high.scale} color={color}/>
  </g>;
}

function boardTextColor(hex: string, amount: number) {
  const floor = [16, 14, 12];
  const rgb = floor.map((underlay, channel) => {
    const start = 1 + 2 * channel;
    return Math.round(lerp(underlay, Number.parseInt(hex.slice(start, start + 2), 16), amount));
  });
  return `rgb(${rgb.join(',')})`;
}

export function BrassGamePlinth({t, heaps, opacity = 1, stonesOpacity = 1, fps = 30}: {
  t: number; heaps?: readonly number[]; opacity?: number; stonesOpacity?: number; fps?: number;
}) {
  const firstGame = t < 34.8;
  const closing = t > 160;
  const gameMoves = gameMovesAt(t);
  const initial = heaps ?? gameMoves[0].before;
  const roll = heaps ? {before: heaps, after: heaps, progress: 1} : countMotionAt(t);
  const inMotion = heaps ? undefined : gameMoves.find(move => t >= move.timeSec && t < move.timeSec + flightDuration);
  const ruleOne = ramp(t, cue(3), 8.93) * (1 - slide(t, 12.8, 13.18));
  const ruleTwo = slide(t, 13.18, 14.6) * (1 - slide(t, 17.8, 18.54));
  const beacon = ramp(t, cue(4), 15.68) * ruleTwo;
  const intro = lerp(.76, 1, ramp(t, cue(2), 4.65));
  const outcome = firstGame ? cue(9) : cue(14);
  const win = heaps ? 0 : ramp(t, outcome + .49, outcome + .66);
  const positionsSwitch = closing && t >= 170.05;
  const identityOpacity = closing ? 1 - slide(t, 169.68, 170.05) + ramp(t, 170.05, 170.4) : intro;
  const transfer = closing ? slide(t, 170.45, 172.85) : 0;
  const readRoles = ramp(t, 3.8, 4.55);
  const demoQuantity = t < 9.58 ? 1 : t < 10.46 ? 3 : 4;
  const guidance = demoQuantity === 1 ? '取 1 颗' : demoQuantity === 3 ? '取多颗' : '也可取整堆';
  const demoLow = stoneY(3) + 2 * 64 * ramp(t, 9.58, 9.94) + 64 * ramp(t, 10.46, 10.83);
  const demoUpper = stoneY(3);
  const demoJawLeft = heapX[2] - jawDistance(ruleOne, 1) - 8;
  const guideY = demoUpper - 49 + 7;
  const calloutEnd = demoJawLeft - 16;
  const focusVariant = (3 + 2 * 2) % 4;
  const focus = laidPosition(2, 3);
  const countLight = 1 - .88 * Math.max(ruleTwo, win);

  function renderStone(heap: number, index: number) {
    const removed = heaps ? undefined : gameMoves.find(move => move.heap - 1 === heap &&
      index >= move.after[heap] && index < move.before[heap] && t >= move.timeSec);
    if (removed || (ruleTwo > 0 && heap === 2 && index === 3)) return null;
    const pos = laidPosition(heap, index);
    const selected = heap === 2 && index >= 4 - demoQuantity ? ruleOne : 0;
    return <FacetedStone key={heap * 10 + index} {...pos} variant={(index + heap * 2) % 4} base={index === 0} liveProjection={true}
      scale={lerp(.974, 1, slide(t, 0, 3.5))} t={lerp(t, 14.6, ruleTwo)} tint={softGold} selected={selected} opacity={intro}/>;
  }

  return <g opacity={opacity}>
    <TableGeometry t={t}/>
    <CollectingRail player="first" y={upperRailY} color={gold}/>
    <CollectingRail player="second" y={lowerRailY} color={softSilver}/>
    <g opacity={readRoles * identityOpacity}>
      {label(500, 629, positionsSwitch ? '对手 · 先手' : '我 · 先手', 29, positionsSwitch ? silver : gold)}
      {label(500, 1344, positionsSwitch ? '我 · 后手' : '你 · 后手', 29, positionsSwitch ? gold : silver)}
    </g>
    {closing && t > 169 && <g opacity={ramp(t,169,169.36)}
      transform={`translate(803 ${lerp(upperRailY, lowerRailY, transfer)})`}>
      {path('M-17 0 0-14 17 0 0 14Z', gold, 1, 1.35)}{core(0, 0, 5, 1)}
    </g>}
    {heapX.map((x, index) => <g key={x}>
        <g data-game-label={`heap-${roman[index]}`}>{label(x, 715, roman[index], 23, boardTextColor(gold, countLight))}</g>
        <g data-game-label={`count-${roman[index]}`}>
          <DigitRoll x={x} y={1180} before={roll.before[index]} after={roll.after[index]} progress={roll.progress}
            size={30} color={boardTextColor(ink, countLight)}/>
        </g>
    </g>)}
    <g opacity={stonesOpacity * (1 - .72 * ruleTwo)} style={ruleTwo > 0 ? {filter: `blur(${2.5 * ruleTwo}px)`} : undefined}>
      {initial.flatMap((n, heap) => Array.from({length: n}, (_, index) => renderStone(heap, index)))}
    </g>
    {ruleTwo > 0 && <g opacity={stonesOpacity}>
      <StoneProjection {...focus} variant={focusVariant} size={1} lift={ruleTwo * 100} reflect={false} opacity={1} live={true}/>
      <FacetedStone x={lerp(focus.x, 500, ruleTwo)} y={lerp(focus.y, 953, ruleTwo) - 35 * Math.sin(Math.PI * ruleTwo)}
        variant={focusVariant} scale={lerp(1, 1.45, ruleTwo)} t={t} selected={.65 * beacon} shadow={false}/>
    </g>}
    {ruleOne > 0 && <g opacity={ruleOne}>
      <ExtractionCaliper x={heapX[2]} firstY={demoUpper} lastY={demoLow} grip={ruleOne} color={softGold} rulesDemo={true}/>
      <g data-b03-callout="guide">{line(demoJawLeft - 12, guideY, demoJawLeft, guideY, gold, .8, .72)}</g>
      <g data-game-label="rule-take" data-b03-callout="label" data-b03-label-end={calloutEnd}
        transform={`translate(${calloutEnd} 0)`}>{label(0, guideY + 8, guidance, 23, ink, 'end')}</g>
    </g>}
    {beacon > 0 && <g opacity={beacon}>
      <circle cx={500} cy={953} r={133} fill="none" stroke={gold} strokeOpacity=".66" strokeWidth="1.35"
        pathLength={1} strokeDasharray="1" strokeDashoffset={1 - beacon} transform="rotate(-90 500 953)"/>
      {path('M353 953h13M634 953h13', gold, .58, 1.1)}
      <g opacity={ramp(t, 14.77, 15.91)}>{label(500, 1127, '末子 = 胜', 29, ink)}</g>
    </g>}
    {inMotion && <>
      {Array.from({length: inMotion.removed}, (_, j) => {
        const index = inMotion.after[inMotion.heap - 1] + j;
        return <FlyingStone key={index} move={inMotion} index={index} t={t} fps={fps}/>;
      })}
      <FlightCaliper move={inMotion} t={t}/>
    </>}
    {win > 0 && <g opacity={win}>
      <circle cx={500} cy={963} r={110} fill="url(#nimWinField)" stroke={gold} strokeWidth="1.4"/>
      <circle cx={500} cy={963} r={99} fill="none" stroke={gold} strokeOpacity=".58" strokeWidth="1" strokeDasharray="2 8"/>
      {path('M500 862v12M500 1052v12M399 963h12M589 963h12', gold, .86, 1.45)}
      {label(500, 957, '胜', 32, ink)}
      {label(500, 1002, firstGame ? '1 : 0' : '2 : 0', 28, gold)}
    </g>}
  </g>;
}

export function StoneCloseup() {
  const zoom = 2.92;
  const groundY = 1142;
  return <>
    <TableGeometry t={6.4}/>
    <FacetedStone x={338} y={groundY - contact(0) * zoom} scale={zoom} variant={0} base={true} t={6.4}/>
    {[0, 1, 2, 3].map(index => <FacetedStone key={index} x={736 + (laidPosition(2, index).x - heapX[2]) * 1.1}
      y={groundY - contact(index) * 1.25 - index * 80} scale={1.25} variant={index} base={index === 0} t={6.4}/>)}
  </>;
}
