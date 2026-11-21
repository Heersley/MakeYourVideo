import React from 'react';
import {core, gold, ink, label, lerp, line, path, ramp, rust, silver, slide} from './stage';

export const weightColumns = [350, 520, 690] as const;
export const weightRows = [760, 920, 1080] as const;
export const weightWidths = [136, 68, 34] as const;
const weights = [4, 2, 1] as const;
const rowLabels = ['Ⅰ', 'Ⅱ', 'Ⅲ'] as const;
const oldHeaps = [1, 4, 6] as const;
const zeroHeaps = [1, 4, 5] as const;
const brokenHeaps = [1, 1, 5] as const;
const emptyHeaps = [0, 0, 0] as const;
const pale = '#F0D594';
const railProfile = 'M111 660L147 603L189 637L211 702V1248L184 1322L145 1361L111 1309V1197L139 1134V800L111 746Z M889 660L853 603L811 637L789 702V1248L816 1322L855 1361L889 1309V1197L861 1134V800L889 746Z';
const show = (t: number, from: number) => ramp(t, from, from + .35);
const bitAt = (heap: number, weight: number) => Number(Boolean(heap & weight));
const ringLine = (x: number, y: number, r: number, color = gold, opacity = .5) => (
  <circle cx={x} cy={y} r={r} fill="none" stroke={color} strokeWidth={1.4} opacity={opacity}/>
);

const metalDefinitions = (
  <defs>
    <linearGradient id="nim-proof-brass" x2="0" y2="1">
      <stop stopColor="#514029"/><stop offset=".24" stopColor="#322619"/>
      <stop offset=".6" stopColor="#1A1611"/><stop offset="1" stopColor="#281E14"/>
    </linearGradient>
    <linearGradient id="nim-proof-face" x2="0" y2="1">
      <stop stopColor="#4B3A27"/><stop offset=".16" stopColor="#413223"/>
      <stop offset=".48" stopColor="#352A1D"/><stop offset=".74" stopColor="#271E14"/>
      <stop offset="1" stopColor="#493622"/>
    </linearGradient>
    <linearGradient id="nim-proof-focus" x2="1" y2="0">
      <stop stopColor={gold} stopOpacity="0"/><stop offset=".5" stopColor={gold} stopOpacity=".37"/>
      <stop offset="1" stopColor={gold} stopOpacity="0"/>
    </linearGradient>
    <linearGradient id="nim-proof-rail-metal" x2="0" y2="1">
      <stop stopColor="#372B1F"/><stop offset=".18" stopColor="#514031"/>
      <stop offset=".47" stopColor="#433326"/><stop offset=".76" stopColor="#4C3B2A"/>
      <stop offset="1" stopColor="#35291D"/>
    </linearGradient>
    <radialGradient id="nim-proof-rim-light">
      <stop stopColor="#ECD1A2" stopOpacity=".88"/>
      <stop offset=".27" stopColor="#D1AE7D" stopOpacity=".68"/>
      <stop offset=".61" stopColor="#AC8457" stopOpacity=".35"/>
      <stop offset="1" stopColor="#6A4D31" stopOpacity="0"/>
    </radialGradient>
    <clipPath id="nim-proof-rails-clip">
      <path d={railProfile}/>
    </clipPath>
  </defs>
);

export function BinaryWeightBrick({x, y, width, on, opacity = 1}: {
  x: number; y: number; width: number; on: boolean; opacity?: number;
}) {
  const left = x - width / 2;
  const right = x + width / 2;
  const outline = `M${left} ${y - 24} L${left + 7} ${y - 32} H${right - 7} L${right} ${y - 24} V${y + 23} L${right - 7} ${y + 31} H${left + 7} L${left} ${y + 23}Z`;
  if (!on) return <g opacity={opacity}>
    {path(outline, '#77674E', .7, 1.25, {strokeDasharray: '3 4'})}
    {line(left + 4, y + 35, right - 4, y + 35, '#635742', 1, .5)}
  </g>;
  return <g opacity={opacity}>
    <path d={outline} fill="url(#nim-proof-brass)" stroke={gold} strokeWidth={1.55}/>
    {path(`M${left + 6} ${y - 19} L${left + 11} ${y - 25} H${right - 11} L${right - 6} ${y - 19} V${y + 18} L${right - 11} ${y + 23} H${left + 11} L${left + 6} ${y + 18}Z`, gold, .4, .8)}
    {line(left + 7, y - 31, right - 7, y - 31, pale, 1.7, .74)}
    {line(left + 7, y + 34, right - 7, y + 34, gold, .8, .68)}
    {Array.from({length: Math.floor((width - 14) / 7)}, (_, tick) => {
      const tx = left + 9 + tick * 7;
      return <React.Fragment key={tick}>{line(tx, y + 18, tx, y + (tick % 4 === 0 ? 10 : 14), gold, .8, .54)}</React.Fragment>;
    })}
  </g>;
}

function ProofEdgeRails({t}: {t: number}) {
  const angle = t * Math.PI * 2 / 1.68;
  const leftY = 984 + 229 * Math.sin(angle);
  const rightY = 984 - 229 * Math.cos(angle);
  return <g aria-hidden="true">
    <path d={railProfile} fill="url(#nim-proof-rail-metal)" stroke={gold} strokeOpacity={.54} strokeWidth={1.1}/>
    {path('M133 670L150 642L177 660L198 708V1240L178 1297L150 1328L132 1302 M867 670L850 642L823 660L802 708V1240L822 1297L850 1328L868 1302', '#120D08', .65, 8)}
    <g clipPath="url(#nim-proof-rails-clip)">
      <ellipse cx={163} cy={leftY} rx={139} ry={226} fill="url(#nim-proof-rim-light)" opacity={.54}/>
      <ellipse cx={837} cy={rightY} rx={139} ry={226} fill="url(#nim-proof-rim-light)" opacity={.54}/>
      {Array.from({length: 44}, (_, i) => <React.Fragment key={i}>
        {line(184 - (i % 4 === 0 ? 13 : 7), 670 + i * 14, 191, 670 + i * 14, gold, .65, .49)}
        {line(809, 670 + i * 14, 816 + (i % 4 === 0 ? 13 : 7), 670 + i * 14, gold, .65, .49)}
      </React.Fragment>)}
    </g>
    {path('M145 642L173 663L197 710V1241L173 1304 M855 642L827 663L803 710V1241L827 1304', gold, .5, 1.1)}
  </g>;
}

type MatrixProps = {
  heaps: readonly number[];
  t: number;
  opacity?: number;
  showResult?: boolean;
  showHeaders?: boolean;
  phase?: number;
  resolve?: readonly number[];
  stoneMorph?: readonly number[];
  previous?: readonly number[];
  change?: number;
  changedRow?: number;
};

export function BinaryWeightMatrix({heaps, t, opacity = 1, showResult = false, showHeaders = true,
  phase = 1, resolve, stoneMorph, previous, change = 1, changedRow}: MatrixProps) {
  return <g opacity={opacity}>
    {metalDefinitions}
    <g opacity={phase}><ProofEdgeRails t={t}/></g>
    <g opacity={phase}>
      {path('M222 673 H779 M222 1161 H779', gold, .49, 1.5)}
      {weightColumns.map((x, col) => <g key={x}>
        {line(x, 673, x, 1159, gold, 1, .25)}
        {path(`M${x - 19} 672h38 M${x} 668v8`, gold, .69, 1.05)}
        {showHeaders && label(x, 643, weights[col], 30, gold)}
      </g>)}
      {weightRows.map((y, row) => <g key={y}>
        <path d={`M217 ${y - 37}l14 -17h530l20 17v74l-20 17H231l-14 -17Z`} fill="url(#nim-proof-face)" stroke="#7C6645" strokeWidth={1.0}/>
        {path(`M232 ${y - 45}H759 M232 ${y + 46}H759`, gold, .42, .8)}
        {path(`M229 ${y - 29}v58 M769 ${y - 29}v58`, gold, .6, 1.4)}
        {label(248, y + 8, rowLabels[row], 22, gold)}
        {changedRow === row && path(`M219 ${y - 43}l10 -12h532l21 17v76l-21 17H229l-10 -12`, gold, .73, 1.8)}
      </g>)}
    </g>
    {weightRows.map((y, row) => <g key={y} opacity={phase}>
      {weightColumns.map((x, col) => {
        const on = bitAt(heaps[row], weights[col]);
        const old = previous === undefined ? on : bitAt(previous[row], weights[col]);
        const arrive = on && stoneMorph ? slide(stoneMorph[row] ?? 1, .82, 1) : 1;
        return <g key={x} opacity={arrive}>
          <BinaryWeightBrick x={x} y={y} width={weightWidths[col]} on={Boolean(on)} opacity={old === on ? 1 : change}/>
          {old !== on && change < 1 && <BinaryWeightBrick x={x} y={y} width={weightWidths[col]} on={Boolean(old)} opacity={1 - change}/>}
          {label(x, y + 7, change < .5 ? old : on, 23, (change < .5 ? old : on) ? ink : '#9A8C71')}
        </g>;
      })}
    </g>)}
    {showResult && <g opacity={phase * (resolve === undefined ? 1 : Math.max(...resolve))}>
      {label(246, 1223, 'XOR', 23, gold)}
      {line(220, 1184, 781, 1184, gold, 1.8, .72)}
      {weightColumns.map((x, col) => {
        const result = heaps.reduce((value, heap) => value ^ bitAt(heap, weights[col]), 0);
        const former = previous?.reduce((value, heap) => value ^ bitAt(heap, weights[col]), 0) ?? result;
        const digit = change < .5 ? former : result;
        const exposure = resolve?.[col] ?? 1;
        return <g key={x} opacity={exposure}>
          {path(`M${x} 1165v19 m-22 0v53h44v-53`, gold, digit ? .79 : .46, 1.2)}
          {label(x, 1225, digit, 28, digit ? pale : silver)}
        </g>;
      })}
    </g>}
  </g>;
}

function signalRail(x: number, y0: number, y1: number, p: number, color = gold) {
  return <g opacity={Math.min(1, p * 5)}>
    {line(x, y0, x, y1, color, 1.1, .23)}
    {line(x, y0, x, lerp(y0, y1, p), color, 2.5, .89)}
    {core(x, lerp(y0, y1, p), 3.1, .75)}
  </g>;
}

function StateBadges({t, change}: {t: number; change: number}) {
  const opacity = ramp(t, 71.15, 71.75);
  const selection = lerp(354, 658, change);
  return <g opacity={opacity}>
    {path('M267 1299h174m129 0h174M354 1299q0 -54 151 -54t153 54', gold, .54, 1.45)}
    {path('M271 1314h-11v38h11 M437 1314h11v38h-11 M575 1314h-11v38h11 M741 1314h11v38h-11', gold, .52, 1.25)}
    {core(selection, 1299, 4, .9)}
    {label(354, 1342, '非零 · 必胜', 28, change < .5 ? pale : silver)}
    {label(658, 1342, '零态 · 必败', 28, change < .5 ? silver : pale)}
  </g>;
}

function ParityLockArc({x, y0, y1, progress, broken = 0, side = 1}: {
  x: number; y0: number; y1: number; progress: number; broken?: number; side?: number;
}) {
  const elbow = x + 45 * side;
  const mid = (y0 + y1) / 2;
  const torsion = broken * 26;
  const stroke = broken > 0 ? rust : gold;
  const intact = Math.max(0, 1 - broken);
  const reveal = {pathLength: 1, strokeDasharray: '1', strokeDashoffset: 1 - progress};
  const left = `M${x} ${y0} C${elbow} ${y0} ${elbow} ${mid - 18} ${elbow} ${mid - torsion}`;
  const right = `M${x} ${y1} C${elbow} ${y1} ${elbow} ${mid + 18} ${elbow} ${mid + torsion}`;
  return <g opacity={progress * intact}>
    {path(left, stroke, .23, 8, reveal)}{path(right, stroke, .23, 8, reveal)}
    {path(left, stroke, .96, 1.7, reveal)}{path(right, stroke, .96, 1.7, reveal)}
    <path d={`M${elbow} ${mid - 7}l7 7 -7 7 -7 -7Z`} fill={broken ? '#381C18' : '#292217'} stroke={stroke} strokeWidth={1.3} opacity={intact}/>
  </g>;
}

function ProofPillars({t, opacity}: {t: number; opacity: number}) {
  const titles = ['终点态 = 0', '零态必破', '非零必归零'];
  return <g opacity={opacity}>
    {metalDefinitions}
    <ProofEdgeRails t={t}/>
    {path('M318 697v502', gold, .55, 2.0)}
    {titles.map((title, i) => {
      const y = 751 + i * 190;
      const p = ramp(t, 83.8 + i * .24, 86.1 + i * .24);
      const c = i === 0 ? pale : gold;
      return <g key={title} opacity={p}>
        <path d={`M318 ${y - 60}h408l46 42v36l-46 42H318l-60 -60Z`} fill="url(#nim-proof-face)" stroke={gold} strokeOpacity={.46}/>
        {path(`M318 ${y - 50}h${lerp(20, 406, p)} M318 ${y + 50}h${lerp(20, 406, p)}`, c, .62, 1.3)}
        {core(318, y, 5, i === 0 ? 1 : .65)}
        {label(374, y + 10, `0${i + 1}`, 29, c)}
        {label(538, y + 13, title, 39, i === 0 ? ink : silver)}
        {Array.from({length: 12}, (_, j) => <React.Fragment key={j}>{line(680 + j * 5, y + 29, 680 + j * 5, y + (j % 3 === 0 ? 19 : 24), gold, .8, .6)}</React.Fragment>)}
      </g>;
    })}
  </g>;
}

function TerminalPlinth({t}: {t: number}) {
  const appearance = show(t, 91.2);
  return <g opacity={appearance}>
    {path('M278 1273h446l39 16 -39 14H278l-39 -14Z M260 1291h482', gold, .62, 1.4, {fill: 'url(#nim-proof-face)'})}
    {[350, 520, 690].map((x) => <g key={x}>
      <ellipse cx={x} cy={1289} rx={22} ry={7} fill="#100D0A" stroke={gold} strokeOpacity={.57}/>
      {line(x, 1269, x, 1280, gold, 1.15, .63)}
    </g>)}
    {label(500, 1344, '无子可取', 32, silver)}
  </g>;
}

function ParityOverlay({t, opacity, change}: {t: number; opacity: number; change: number}) {
  const p4 = ramp(t, 96.15, 98.0);
  const p1 = ramp(t, 97.2, 99.0);
  const breakAt = ramp(t, 104.6, 105.22);
  return <g opacity={opacity}>
    <ParityLockArc x={422} y0={920} y1={1080} progress={p4} broken={breakAt}/>
    <ParityLockArc x={715} y0={760} y1={1080} progress={p1}/>
    {change >= .5 && <g opacity={change}>
      {path('M406 1080h25l14 -12m268 -148h23', rust, .9, 1.8)}
      <path d="M444 1064l5 5 -5 5 -5 -5Z M737 915l5 5 -5 5 -5 -5Z" fill={rust}/>
    </g>}
    {weightColumns.map((x, col) => {
      const changed = change >= .5 && col !== 1;
      const p = [p4, show(t, 96.9), p1][col];
      const detail = col === 1 ? '偶 · 零个 1' : changed ? `奇 · ${col === 0 ? 1 : 3} 个 1` : '偶 · 成对';
      return <g key={x} opacity={p}>{label(x, 1301, detail, 24, changed ? rust : silver)}</g>;
    })}
  </g>;
}

function HighestBit({t, opacity}: {t: number; opacity: number}) {
  const start = show(t, 111.0);
  const x = lerp(350, 520, slide(t, 111.0, 112.1));
  const target = ramp(t, 115.35, 118.95);
  return <g opacity={opacity * start}>
    <rect x={x - 57} y={681} width={114} height={478} fill="url(#nim-proof-focus)" opacity={.28}/>
    {path(`M${x - 67} 699v-17h134v17 M${x - 67} 1142v18h134v-18`, gold, .83, 1.8)}
    {signalRail(581, 1190, 1080, target)}
    {path('M472 1038h17m-17 0v18m96 -18h-17m17 0v18m-96 66h17m-17 0v-18m96 18h-17m17 0v-18', pale, target, 2.1)}
    {target > 0 && <g opacity={target}>{label(520, 1300, '奇数个 1 → 选第三堆', 27, pale)}</g>}
  </g>;
}

function renderMatrixProof(t: number, opacity: number) {
  const introToEvens = 1 - show(t, 94.6);
  const evensToHighest = 1 - show(t, 108.4);
  const entry = show(t, 89.35);
  const rowChange = ramp(t, 104.6, 105.7);
  const highest = show(t, 108.75);
  const swap = Math.max(show(t, 94.95), highest);
  const heaps = highest > 0 ? oldHeaps : rowChange > 0 ? brokenHeaps : zeroHeaps;
  const oldRow = highest > 0 ? brokenHeaps : rowChange > 0 ? zeroHeaps : emptyHeaps;
  const amount = highest > 0 ? highest : rowChange > 0 ? rowChange : show(t, 94.95);
  return <g opacity={opacity * entry}>
    <BinaryWeightMatrix heaps={swap > 0 ? heaps : emptyHeaps} previous={swap > 0 ? oldRow : undefined} change={swap > 0 ? amount : 1} t={t} showResult={true} changedRow={t > 103 && t < 108.75 ? 1 : undefined}/>
    <g opacity={introToEvens}><TerminalPlinth t={t}/></g>
    <g opacity={1 - introToEvens}>
      <rect x={214} y={1259} width={570} height={103} fill="#11100C" opacity={.25 * evensToHighest}/>
      <ParityOverlay t={t} opacity={evensToHighest} change={rowChange}/>
    </g>
    <HighestBit t={t} opacity={highest}/>
  </g>;
}

function tray(x: number, y: number) {
  return <g>
    {path(`M${x} ${y}l-62 156m62 -156l62 156`, gold, .67, 1.45)}
    <path d={`M${x - 73} ${y + 156}h146q-19 29 -73 29t-73 -29Z`} fill="url(#nim-proof-brass)" stroke={gold} strokeWidth={1.7}/>
    {path(`M${x - 66} ${y + 161}h132 M${x - 55} ${y + 172}q55 17 110 0`, gold, .51, 1.05)}
    {core(x, y, 3.5, .85)}
  </g>;
}

function ScaleFoundation() {
  return <g>
    <path d="M268 751H389L445 710H555L611 751H732L776 792V1008L730 1071H625L573 1120H427L375 1071H270L224 1008V792Z"
      fill="none" stroke="#553E28" strokeOpacity=".67"/>
    <path d="M225 792L268 751H389L445 710H555L611 751H732L775 792L763 796L727 765H605L550 724H450L394 765H273L237 796Z
      M224 1008L270 1071H375L427 1120H573L625 1071H730L776 1008L765 1000L724 1058H621L567 1109H433L379 1058H276L235 1000Z"
      fill="url(#nim-proof-face)" fillOpacity=".72"/>
    {path('M234 812v-16l39 -35h116l59 -40h104l59 40h116l39 35v16 M235 992v13l40 55h102l54 48h138l54 -48h102l40 -55v-13', gold, .45, 1.1)}
    {path('M282 813h41 M677 813h41 M282 1020h41 M677 1020h41', gold, .49, 1.05)}
  </g>;
}

function BinaryBalanceScale({t, opacity}: {t: number; opacity: number}) {
  const reveal = ramp(t, 122.0, 123.85);
  const comparison = ramp(t, 128.75, 132.15);
  const weightsChange = ramp(t, 124.2, 126.75);
  const remove = ramp(t, 124.2, 125.8);
  const add = ramp(t, 124.33, 126.02);
  const angle = lerp(0, 10.5, weightsChange);
  const radians = angle * Math.PI / 180;
  const center = {x: 500, y: 845};
  const left = {x: center.x - 219 * Math.cos(radians), y: center.y - 219 * Math.sin(radians)};
  const right = {x: center.x + 219 * Math.cos(radians), y: center.y + 219 * Math.sin(radians)};
  const textOpacity = 1 - show(t, 128.4);
  const resultAppearance = show(t, 124.68);
  const proofZero = show(t, 132.82);
  return <g opacity={opacity * reveal}>
    {metalDefinitions}
    <ProofEdgeRails t={t}/>
    <ScaleFoundation/>
    <g opacity={textOpacity}>
      {label(442, 629, '110  ⊕  011  =', 34, ink)}
      <g opacity={resultAppearance}>
        {label(644, 629, '101', 34, pale)}
        {label(500, 674, '权值 4 不变 · 权值 2 翻零 · 权值 1 翻一', 22, gold)}
      </g>
    </g>
    <g opacity={comparison}>
      {label(500, 630, '最高变位的净变化', 32, ink)}
      {label(500, 670, '−2 + 1 = −1', 32, pale)}
    </g>
    <path d="M470 1075l16 -197h28l16 197h59l17 16v15H394v-15l17 -16Z" fill="url(#nim-proof-brass)" stroke={gold} strokeOpacity={.61} strokeWidth={1.7}/>
    {path('M410 1092h180 M490 883l-9 185m29 -185l9 185', gold, .68, 1.24)}
    {path('M411 835a90 90 0 0 1 178 0 M427 833a74 74 0 0 1 146 0', gold, .53, 1.5)}
    {Array.from({length: 25}, (_, i) => {
      const a = Math.PI * (1 + i / 24);
      const outer = 91;
      const inner = i % 4 === 0 ? 76 : 82;
      return <React.Fragment key={i}>{line(500 + inner * Math.cos(a), 841 + inner * Math.sin(a), 500 + outer * Math.cos(a), 841 + outer * Math.sin(a), gold, 1.1, .69)}</React.Fragment>;
    })}
    <g transform={`rotate(${angle} 500 845)`}>
      <path d="M281 845l21 -12h123l38 -14h74l38 14h123l21 12 -21 12H573l-34 14h-78l-34 -14H302Z" fill="url(#nim-proof-brass)" stroke={gold} strokeWidth={1.45}/>
      {path('M302 838h125l38 -13h70l38 13h125 M302 852h125l38 13h70l38 -13h125 M500 858l-4 -86 4 -17 4 17 -4 86', pale, .69, 1.35)}
    </g>
    {tray(left.x, left.y)}{tray(right.x, right.y)}
    {core(500, 845, 7.0, .94)}
    {ringLine(500, 845, 21, pale, .86)}{ringLine(500, 845, 28, gold, .45)}
    <BinaryWeightBrick x={left.x - 60 * remove} y={left.y + 126 - 104 * remove} width={68} on={true} opacity={1 - remove}/>
    <BinaryWeightBrick x={right.x + 62 * (1 - add)} y={right.y + 126 - 104 * (1 - add)} width={34} on={true} opacity={add}/>
    <g opacity={show(t, 125.0)}>
      {label(281, 1115, '−2', 30, silver)}
      {label(719, 1115, '+1', 30, pale)}
    </g>
    <g opacity={comparison}>
      {label(266, 1173, <>2<tspan baselineShift="super" fontSize={17}>k</tspan></>, 26, pale)}
      {label(266, 1237, <>2<tspan baselineShift="super" fontSize={17}>k</tspan> − 1</>, 25, silver)}
      <path d={`M360 1152h${360 * comparison}v18H360Z`} fill="url(#nim-proof-brass)" stroke={pale} strokeWidth={1.45}/>
      {[180, 90, 45, 22.5].map((segment, index, segments) => {
        const start = segments.slice(0, index).reduce((sum, size) => sum + size, 360);
        const length = segment * comparison;
        return <path key={segment} d={`M${start} 1216h${length}v18h${-length}Z`} fill="url(#nim-proof-face)" stroke={gold} strokeOpacity={.75} strokeWidth={1.05}/>;
      })}
      {path('M720 1144v100 M697.5 1234v10', gold, .62, 1.15, {strokeDasharray: '3 4'})}
      {path('M697.5 1250H720 M697.5 1244v12 M720 1244v12', pale, .77, 1.1)}
    </g>
    <g opacity={proofZero}>
      {zeroHeaps.map((heap, row) => <g key={row}>
        {label(271, 1284 + 37 * row, rowLabels[row], 22, silver)}
        {weights.map((weight, col) => <React.Fragment key={weight}>
          {label(329 + col * 39, 1284 + 37 * row, bitAt(heap, weight), 23, row === 2 ? pale : ink)}
        </React.Fragment>)}
      </g>)}
      {path('M427 1263h12v103h-12 M448 1314h45m-8 -7l8 7 -8 7', gold, .67, 1.5)}
      {label(636, 1303, '5 < 6', 30, pale)}
      {label(636, 1353, 'XOR 011 → 000', 29, ink)}
    </g>
  </g>;
}

function gears(t: number, x: number, y: number, color: string, turn: number) {
  const spin = turn + (t - 137.4) * 11;
  return <g>
    {ringLine(x, y, 130, color, .84)}{ringLine(x, y, 122, color, .41)}{ringLine(x, y, 111, color, .39)}
    {Array.from({length: 30}, (_, i) => {
      const a = (i * 12 + spin) * Math.PI / 180;
      const inner = i % 5 === 0 ? 139 : 145;
      return <React.Fragment key={i}>{line(x + inner * Math.cos(a), y + inner * Math.sin(a), x + 152 * Math.cos(a), y + 152 * Math.sin(a), color, i % 5 === 0 ? 2.4 : 1.25, .82)}</React.Fragment>;
    })}
  </g>;
}

function StateMachineRings({t}: {t: number}) {
  const appear = ramp(t, 135.75, 137.8);
  const join = ramp(t, 137.4, 138.9);
  const end = show(t, 140.06);
  const turn = Math.sin(t * 1.9) * 9;
  const states = [[1, 4, 6], [1, 4, 5], [1, 1, 5], [1, 1, 0], [0, 1, 0], [0, 0, 0]];
  const current = t < 137.4 ? 0 : Math.min(5, Math.floor((t - 137.4) / .51));
  const remaining = states[current];
  return <g opacity={appear}>
    {metalDefinitions}
    <ProofEdgeRails t={t}/>
    <ellipse cx={312} cy={907} rx={145} ry={139} fill="url(#nim-proof-face)" opacity={.86}/>
    <ellipse cx={688} cy={907} rx={145} ry={139} fill="url(#nim-proof-face)" opacity={.75}/>
    {gears(t, 312, 907, gold, turn)}
    {gears(t, 688, 907, silver, -turn)}
    {label(312, 920, 'XOR ≠ 0', 34, pale)}
    {label(688, 920, 'XOR = 0', 34, silver)}
    <g opacity={join}>
      {path('M327 772C384 651 645 652 673 773', gold, .83, 2.5)}
      {path('M662 761l11 12 6 -17', gold, .92, 2.5)}
      {path('M717 1046C703 1172 350 1177 305 1046 M686 1042C638 1110 353 1128 315 1045 M654 1046C572 1102 368 1101 328 1047', silver, .66, 1.5)}
      {path('M300 1060l5 -14 12 9 M309 1058l6 -13 12 8 M321 1057l7 -10 13 5', silver, .79, 1.46)}
      {label(500, 665, '选一步归零', 25, pale)}
      {label(500, 1192, '有子时，每步都破零', 25, silver)}
      {label(500, 1270, `(${remaining.join(', ')})`, 35, ink)}
      <g opacity={end}>{label(500, 1323, '无子可取 · 终点', 26, gold)}</g>
    </g>
  </g>;
}

function XorDemonstration({t}: {t: number}) {
  const resultReveal = [66.8, 67.43, 68.11].map((start) => ramp(t, start, start + .55));
  const truthTable = show(t, 64.35) * (1 - show(t, 70.8));
  const change = ramp(t, 80.4, 81.57);
  return <>
    <BinaryWeightMatrix heaps={change > 0 ? zeroHeaps : oldHeaps} previous={change > 0 ? oldHeaps : undefined} change={change} t={t} showResult={t > 66.8} resolve={resultReveal}/>
    <g opacity={truthTable}>{label(500, 587, '1 ⊕ 1 = 0    ·    1 ⊕ 0 = 1', 29, pale)}</g>
    <g opacity={1 - show(t, 70.8)}>
      <ParityLockArc x={424} y0={920} y1={1080} progress={ramp(t, 66.8, 67.35)}/>
      {signalRail(570, 1090, 1175, resultReveal[1])}
      {signalRail(728, 768, 1175, resultReveal[2])}
    </g>
    <StateBadges t={t} change={change}/>
  </>;
}

export function ProofStage({t}: {t: number}) {
  if (t < 83.8) return <XorDemonstration t={t}/>;
  const pillars = 1 - show(t, 89.0);
  const matrix = 1 - show(t, 121.4);
  const balance = 1 - show(t, 135.4);
  return <>
    {pillars > 0 && <ProofPillars t={t} opacity={pillars}/>}
    {t > 89.35 && matrix > 0 && renderMatrixProof(t, matrix)}
    {t > 122.0 && balance > 0 && <BinaryBalanceScale t={t} opacity={balance}/>}
    {t > 135.75 && <StateMachineRings t={t}/>}
  </>;
}
