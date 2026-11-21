import {western} from './Fonts';
import {FacetedStone, heapX, stoneY} from './Game';
import {core, dim, gold, ink, label, lerp, line, path, ramp, score, silver, slide} from './stage';

const recap = [score.moves.slice(0, 5), score.moves.slice(5, 10)].map(moves => [
  moves[0].before,
  ...moves.map(move => move.after),
]);

function MetalReflections({t, y, width, depth, phase = 0}: {
  t: number; y: number; width: number; depth: number; phase?: number;
}) {
  const angle = t * Math.PI * 2 / 1.62 + phase;
  return <>
    <ellipse cx={500 + width * .33 * Math.sin(angle)} cy={y}
      rx={width * .42} ry={depth} fill="url(#nimEpilogueSpecular)" opacity={.46 + .09 * Math.cos(angle)}/>
    <ellipse cx={500 - width * .30 * Math.cos(angle)} cy={y + depth * .13}
      rx={width * .35} ry={depth * .83} fill="url(#nimEpilogueSpecular)" opacity={.38 + .075 * Math.sin(angle)}/>
  </>;
}

function RecapTracks({t}: {t: number}) {
  return <g>
    {recap.map((positions, row) => {
      const y = 827 + row * 278;
      const trace = 167 + 670 * slide(t, 142.1 + row * .62, 146.5 + row * .62);
      const glint = 515 + 306 * Math.sin((t - 142) * 2.1 + row * 1.3);
      const railSurface = 'M149 ' + (y - 24) + ' H851 L877 ' + (y + 11) +
        ' L853 ' + (y + 55) + ' H147 L123 ' + (y + 11) + ' Z';
      const railLight = 'nimRecapFace' + row;
      return <g key={row}>
        {label(130, y - 120, row === 0 ? '第一局' : '第二局', 28, gold, 'start')}
        {line(130, y - 97, 874, y - 97, gold, 1.15, .46)}
        <clipPath id={railLight}><path d={railSurface}/></clipPath>
        <path d={railSurface} fill="url(#nimEpilogueMetal)"/>
        <g clipPath={'url(#' + railLight + ')'}>
          <MetalReflections t={t} y={y + 12} width={690} depth={61} phase={row * 1.65}/>
        </g>
        {line(167, y, 837, y, dim, 2.1, .86)}
        {line(167, y, trace, y, gold, 2.1, .86)}
        {line(149, y + 51, 851, y + 51, gold, .65, .43)}
        {Array.from({length: 35}, (_, i) => {
          const x = 163 + 20 * i;
          return <g key={i}>{line(x, y + 22, x, y + (i % 5 === 0 ? 35 : 29), gold, 1, .32)}</g>;
        })}
        {positions.map((state, step) => {
          const x = 167 + step * 134;
          const own = step % 2 === 1;
          const reveal = step === 0 ? 1 : ramp(t, 142.45 + step * .77 + row * .49, 143.0 + step * .77 + row * .49);
          const color = own ? gold : silver;
          return <g key={step} data-recap-node={state.join(',')}>
            {step > 0 && path('M' + (x - 70) + ' ' + (y - 5) + ' l7 5 -7 5', color, .44 + reveal * .4, 1.5)}
            <path d={'M' + x + ' ' + (y - 12) + ' l12 12 -12 12 -12 -12 Z'} fill="#110e0b" stroke={color} strokeWidth={own ? 1.8 : 1.2} opacity={.52 + reveal * .44}/>
            <circle cx={x} cy={y} r={own ? 3.25 : 2.2} fill={own ? '#FFF6DF' : silver} opacity={.36 + reveal * .62}/>
            {label(x, y - 40, '(' + state.join(',') + ')', 25, own ? gold : ink)}
            {own && <g opacity={reveal}>
              {line(x, y + 39, x, y + 54, gold, 1.1, .68)}
              {label(x, y + 86, 'XOR = 0', 19, gold)}
            </g>}
          </g>;
        })}
        <rect x={glint - 45} y={y + 13} width={90} height={2} fill="url(#nimRecapRail)" opacity=".72"/>
      </g>;
    })}
  </g>;
}

function ArchiveFiligree({x, y, facingX, facingY}: {x: number; y: number; facingX: number; facingY: number}) {
  return <g transform={'translate(' + x + ' ' + y + ') scale(' + facingX + ' ' + facingY + ')'}>
    {path('M0 63 V13 Q0 0 13 0 H63 M8 48 V17 Q8 8 17 8 H48 M16 34 Q34 28 34 16 Q28 34 16 34 Z', gold, .82, 1.1)}
    {path('M22 58 Q22 22 58 22 M31 50 Q31 31 50 31 M3 49 l7 -7 M49 3 l-7 7', gold, .39, 1)}
  </g>;
}

function BoutonArchivalPlate({t}: {t: number}) {
  const arrival = slide(t, 150, 153.65);
  const sweep = slide(t, 150, 153.8);
  const passing = sweep === 1 ? 0 : .14 * Math.sin(Math.PI * sweep);
  const reflection = 76 + 960 * sweep;
  const settling = 1 - arrival;
  const opacity = 1 - ramp(t, 155.4, 155.75);
  const glint = 500 + 245 * Math.sin((t - 148.8) * 1.7);
  return <g opacity={opacity}>
    <path d="M188 1208 H812 L874 1278 L838 1338 H162 L126 1278 Z" fill="url(#nimEpilogueMetal)"/>
    <g clipPath="url(#nimArchiveRest)">
      <MetalReflections t={t} y={1287} width={674} depth={81} phase={.94}/>
    </g>
    {line(177, 1281, 823, 1281, dim, 1, .48)}
    {line(glint - 38, 1277, glint + 38, 1277, gold, 1, .54)}
    {core(glint, 1281, 3.5, .44)}
    <g style={{
      transformOrigin: '500px 957px',
      transform: arrival === 1 ? 'none' : 'perspective(1200px) rotateX(' + 6 * settling + 'deg) rotateY(' + -5 * settling + 'deg)',
      filter: 'none',
    }}>
      <path d="M178 646 H827 L848 669 V1226 L826 1248 H179 L156 1226 V668 Z" fill="#090806" stroke="#282016" strokeWidth="2"/>
      <path d="M183 633 H817 L838 654 V1214 L817 1235 H183 L162 1214 V654 Z" fill="url(#nimPlateFace)" stroke="#A88953" strokeWidth="2.2"/>
      <path d="M183 633 H817 L838 654 V1214 L817 1235 H183 L162 1214 V654 Z" fill="url(#nimArchiveSoftbox)" opacity=".49"/>
      <path d="M190 650 H810 L821 661 V1207 L810 1218 H190 L179 1207 V661 Z" fill="none" stroke="#806C48" strokeWidth="1.2"/>
      <path d="M197 662 H803 L807 666 V1202 L803 1206 H197 L193 1202 V666 Z" fill="none" stroke="#624C33" strokeWidth="1.1"/>
      <g opacity=".52">
        {Array.from({length: 35}, (_, i) => {
          const y = 679 + 14 * i;
          const inset = i % 4 === 0 ? 4 : 0;
          return <g key={i}>
            {line(198, y, 228 + inset, y, '#A48050', .8, .58)}
            {line(772 - inset, y, 802, y, '#A48050', .8, .58)}
          </g>;
        })}
      </g>
      <ArchiveFiligree x={201} y={670} facingX={1} facingY={1}/>
      <ArchiveFiligree x={799} y={670} facingX={-1} facingY={1}/>
      <ArchiveFiligree x={201} y={1197} facingX={1} facingY={-1}/>
      <ArchiveFiligree x={799} y={1197} facingX={-1} facingY={-1}/>
      <g opacity={.63 + .37 * ramp(t, 150, 150.85)} fontFamily={western} fontWeight={400}
        style={{fontSynthesis:'none'}}>
        <text data-qc-text="archives" x={500} y={743} textAnchor="middle" fontSize={26} letterSpacing="2.2" fill={gold}>ANNALS OF MATHEMATICS</text>
        <text data-qc-text="archives" x={500} y={789} textAnchor="middle" fontSize={22} letterSpacing="2.1" fill={gold}>VOL. 3 · 1901–1902</text>
        <text data-qc-text="archives" x={500} y={878} textAnchor="middle" fontSize={31} fill={gold}>Charles L. Bouton</text>
        <text data-qc-text="archives" x={500} y={967} textAnchor="middle" fontSize={35} fill={ink}>Nim, a Game with a</text>
        <text data-qc-text="archives" x={500} y={1039} textAnchor="middle" fontSize={35} fill={ink}>Complete Mathematical Theory</text>
        <text data-qc-text="archives" x={500} y={1138} textAnchor="middle" fontSize={20} letterSpacing="2.1" fill={gold}>HARVARD UNIVERSITY</text>
      </g>
      {line(263, 817, 737, 817, gold, 1, .45)}
      {line(276, 1076, 724, 1076, gold, 1, .52)}
      {path('M500 1069 l7 7 -7 7 -7 -7 Z', gold, .74, 1.25)}
      <path d={'M' + (reflection - 130) + ' 631 h125 l270 606 h-125 Z'} fill="url(#nimArchiveShimmer)" opacity={passing} clipPath="url(#nimArchiveClip)"/>
    </g>
  </g>;
}

function GridPosition({x}: {x: number}) {
  const top = 755;
  const left = x - 48;
  return <g>
    {Array.from({length: 3}, (_, i) => <g key={i}>{line(left + 48 * i, top, left + 48 * i, top + 144, gold, 1, .5)}</g>)}
    {Array.from({length: 4}, (_, i) => <g key={i}>{line(left, top + 48 * i, left + 96, top + 48 * i, gold, 1, .5)}</g>)}
    {path('M' + (x + 34) + ' 755 H' + (x - 39) + ' m7 -5 -7 5 7 5', gold, .9, 1.8)}
    {path('M' + (x + 48) + ' 769 V890 m-5 -8 5 8 5 -8', gold, .9, 1.8)}
    {core(x + 48, top, 6)}
  </g>;
}

function SegmentPosition({x}: {x: number}) {
  return <g>
    {line(x - 77, 836, x + 77, 836, dim, 1.5, .95)}
    {path('M' + (x + 59) + ' 831 Q' + x + ' 742 ' + (x - 59) + ' 831 l2 -9 m-2 9 l9 -2', gold, .73, 1.7)}
    {path('M' + (x + 59) + ' 830 Q' + (x + 28) + ' 779 ' + x + ' 830 l1 -8 m-1 8 l8 -3', gold, .88, 1.7)}
    {[x - 59, x, x + 59].map((p, index) => <g key={p}>
      {line(p, 827, p, 846, index === 2 ? gold : silver, 1.6, .83)}
      {label(p, 873, index, 18, silver)}
    </g>)}
    {core(x + 59, 836, 6)}
  </g>;
}

function TreePosition({x}: {x: number}) {
  const nodes: [number, number][] = [
    [x, 746], [x - 66, 797], [x, 797], [x + 61, 797],
    [x, 847], [x + 37, 847], [x + 83, 847], [x + 83, 899],
  ];
  const edges = [[0, 1], [0, 2], [0, 3], [2, 4], [3, 5], [3, 6], [6, 7]];
  return <g>
    {edges.map(([a, b]) => {
      const [fromX, fromY] = nodes[a];
      const [toX, toY] = nodes[b];
      return <g key={b}>{line(fromX, fromY + 7, toX, toY - 7, gold, 1.35, .72)}</g>;
    })}
    {nodes.map(([px, py], i) => <g key={i}>
      <circle cx={px} cy={py} r={i === 0 ? 6 : 4} fill={i === 0 ? '#FFF6DF' : '#1A1611'} stroke={gold} strokeWidth="1.4"/>
    </g>)}
    {core(x, 746, 6)}
  </g>;
}

function GameEquivalence({t}: {t: number}) {
  const entry = ramp(t, 155.75, 156.5);
  const settle = slide(t, 157.55, 160.8);
  const exit = 1 - ramp(t, 162.2, 162.55);
  return <g>
    <g opacity={entry * exit}>
      <path d="M203 916 H797 L873 1053 L815 1149 H185 L127 1053 Z" fill="url(#nimEpilogueMetal)"/>
      <g clipPath="url(#nimEquivalenceDeck)">
        <MetalReflections t={t} y={1034} width={702} depth={117} phase={.67}/>
      </g>
      {path('M203 916H797 M144 1053H856 M185 1149H815', gold, .26, .84)}
      {path('M383 926L371 1138 M617 926L629 1138', gold, .25, 1, {strokeDasharray: '3 7'})}
    </g>
    {heapX.map((x, column) => {
      const gather = slide(t, 157.8 + column * .3, 159.65 + column * .43);
      const focus = 15 * Math.sin((t - 155.75) * 2.8 + column * 2.1);
      const reveal = entry * ramp(t, 155.75 + column * .11, 156.46 + column * .11);
      const details = reveal * exit * (1 - .67 * settle);
      return <g key={x}>
        <g opacity={details}>
          {label(x, 703, ['方格棋盘', '分段直线', '分枝树'][column], 25, gold)}
          <path d={'M' + (x - 84) + ' 795 Q' + x + ' 623 ' + (x + 84) + ' 795'} fill="none" stroke={gold} strokeWidth="1" strokeDasharray="2 8" opacity=".28"/>
          <path d={'M' + (x - 84) + ' 872 Q' + x + ' 996 ' + (x + 84) + ' 872'} fill="none" stroke={gold} strokeWidth="1" strokeDasharray="2 8" opacity=".28"/>
          {column === 0 ? <GridPosition x={x}/> : column === 1 ? <SegmentPosition x={x}/> : <TreePosition x={x}/>}
        </g>
        <g opacity={exit * reveal}>
          {path('M' + x + ' 915 C' + (x - 44) + ' 923 ' + (x + 34) + ' 948 ' + x + ' 964', gold, .64 * (1 - .48 * settle), 1.1, {strokeDasharray: '3 8'})}
          {core(x + focus, 936, 2.7, .65 * (1 - .45 * settle))}
          {label(x, 1186, 'Grundy 值 ' + (column + 1), 23, gold)}
        </g>
        {Array.from({length: column + 1}, (_, index) => {
          const flow = slide(t, 157.85 + column * .31 + index * .12, 160.1 + column * .34);
          return <FacetedStone
            key={index}
            x={x + (1 - flow) * ((index % 2 === 0 ? 1 : -1) * (35 + 13 * index))}
            y={lerp(936 - index * 26, stoneY(index), flow)}
            opacity={gather * ramp(t, 158.2 + column * .2 + index * .095, 158.8 + column * .27 + index * .14)}
            variant={(index + column * 2) % 4} t={t}
          />;
        })}
      </g>;
    })}
  </g>;
}

export function ZeroTray({t}: {t: number}) {
  const appear = ramp(t, 163.28, 164.2) * (1 - slide(t, 174.4, 174.75));
  if (appear <= 0) return null;
  return <g opacity={appear}>
    <path d="M357 1207H643L670 1236L649 1267H351L330 1236Z"
      fill="#211910" stroke={gold} strokeWidth="1" strokeOpacity=".55"/>
    {line(358, 1262, 642, 1262, dim, .7, .37)}
    {[4, 2, 1].map((weight, column) => {
      const x = 406 + column * 94;
      const locked = ramp(t, 164.25 + column * .52, 165.14 + column * .52);
      return <g key={weight}>
        {label(x - 22, 1244, weight, 23, silver)}
        {path('M' + (x - 6) + ' 1236h14m-4-4 4 4-4 4', gold, .46, .85)}
        <g opacity={locked}>{label(x + 26, 1244, '0', 26, gold)}</g>
        {weight > 1 && <line x1={x + 47} x2={x + 47} y1={1217} y2={1255} stroke={gold} strokeOpacity=".24"/>}
        {column > 0 && <g opacity={1 - locked}>
          <circle cx={x + 17} cy={1253} r="1.8" fill="#FFF6DF"/>
          <circle cx={x + 35} cy={1253} r="1.8" fill="#FFF6DF"/>
          <path d={'M' + (x + 17) + ' 1252q9 -11 18 0'} fill="none" stroke={gold} strokeWidth="1"/>
        </g>}
        {line(x + 14, 1253, x + 38, 1253, gold, 1, .16 + .53 * locked)}
      </g>;
    })}
  </g>;
}

function ClosingEngraving({t}: {t: number}) {
  const show = ramp(t, 174.75, 175.32);
  const safeDrop = slide(t, 178.99, 179.63);
  const settle = slide(t, 179.65, 181.64);
  const exit = 1 - slide(t, 181.38, 182.5);
  const deck = show * (.85 + .15 * settle) * exit;
  const rhombus = 'M169 1118H831L898 1178L839 1276H161L102 1178Z';
  return <g opacity={show * exit}>
    <g opacity={deck}>
      <path d={rhombus} fill="url(#nimClosingDeck)"/>
      <g clipPath="url(#nimClosingDeckClip)">
        <MetalReflections t={t} y={1190} width={768} depth={104} phase={2.17}/>
      </g>
      {path('M178 1261H822 M191 1252H809', gold, .4, .8)}
    </g>
    {heapX.map((x, i) => {
      const fold = slide(t, 174.86 + i * .11, 177.65 + i * .13);
      const center = lerp(x, 500 + (x - 500) * .58, settle);
      const right = center + lerp(lerp(15, 82, fold), 63, settle);
      const left = center - lerp(lerp(15, 82, fold), 63, settle);
      const y = lerp(lerp(stoneY(i), 939 + 35 * i, fold), 1169 + i * 19 * (1 - settle), safeDrop);
      const glint = center + 48 * Math.sin(t * 2.4 + i * 1.4);
      return <g key={x}>
        {path('M' + left + ' ' + y + ' Q' + center + ' ' + (y - 29 * (1 - fold)) + ' ' + right + ' ' + y, gold, .87, 1.6)}
        {line(left + 9, y + 9, right - 9, y + 9, gold, 1, .47 * fold)}
        {Array.from({length: 9}, (_, tick) => {
          const xx = lerp(left + 13, right - 13, tick / 8);
          return <g key={tick}>{line(xx, y + 15, xx, y + (tick % 4 === 0 ? 27 : 21), gold, 1, .52 * fold)}</g>;
        })}
        {core(center, y - 8, lerp(5, 2.4, settle), .85 + .15 * Math.cos(t * 2.8 + i))}
        {core(glint, y + 9, 2.3, .43 * fold)}
      </g>;
    })}
  </g>;
}

export function Epilogue({t}: {t: number}) {
  return <>
    <defs>
      <linearGradient id="nimRecapRail">
        <stop stopColor={gold} stopOpacity="0"/>
        <stop offset=".5" stopColor="#FFF6DF"/>
        <stop offset="1" stopColor={gold} stopOpacity="0"/>
      </linearGradient>
      <linearGradient id="nimEpilogueMetal" x1="0" x2="0" y1="0" y2="1">
        <stop stopColor="#17120D"/>
        <stop offset=".26" stopColor="#3D3124"/>
        <stop offset=".67" stopColor="#48392A"/>
        <stop offset="1" stopColor="#1D170F"/>
      </linearGradient>
      <radialGradient id="nimEpilogueSpecular">
        <stop stopColor="#E9CA96" stopOpacity=".90"/>
        <stop offset=".31" stopColor="#D9B978" stopOpacity=".70"/>
        <stop offset=".69" stopColor="#B48A58" stopOpacity=".28"/>
        <stop offset="1" stopColor="#7C5432" stopOpacity="0"/>
      </radialGradient>
      <radialGradient id="nimArchiveSoftbox" cx=".41" cy=".40" r=".70">
        <stop stopColor="#5C4832"/>
        <stop offset=".56" stopColor="#57412B" stopOpacity=".82"/>
        <stop offset="1" stopColor="#20170E" stopOpacity="0"/>
      </radialGradient>
      <linearGradient id="nimClosingDeck" x1="0" x2="0" y1="0" y2="1">
        <stop stopColor="#17120D" stopOpacity="0"/>
        <stop offset=".45" stopColor="#31251B"/>
        <stop offset=".78" stopColor="#3D3124"/>
        <stop offset="1" stopColor="#1D170F" stopOpacity="0"/>
      </linearGradient>
      <linearGradient id="nimPlateFace" x1="0" x2=".9" y1="0" y2="1">
        <stop stopColor="#211A12"/>
        <stop offset=".53" stopColor="#110F0C"/>
        <stop offset="1" stopColor="#1D170F"/>
      </linearGradient>
      <linearGradient id="nimArchiveShimmer">
        <stop stopColor={gold} stopOpacity="0"/>
        <stop offset=".5" stopColor="#FFF6DF"/>
        <stop offset="1" stopColor={gold} stopOpacity="0"/>
      </linearGradient>
      <clipPath id="nimArchiveClip">
        <path d="M183 633 H817 L838 654 V1214 L817 1235 H183 L162 1214 V654 Z"/>
      </clipPath>
      <clipPath id="nimArchiveRest"><path d="M188 1208 H812 L874 1278 L838 1338 H162 L126 1278 Z"/></clipPath>
      <clipPath id="nimEquivalenceDeck"><path d="M203 916 H797 L873 1053 L815 1149 H185 L127 1053 Z"/></clipPath>
      <clipPath id="nimClosingDeckClip"><path d="M169 1118H831L898 1178L839 1276H161L102 1178Z"/></clipPath>
    </defs>
    {t >= 142 && t < 148.8 && <RecapTracks t={t}/>}
    {t >= 148.8 && t < 155.75 && <BoutonArchivalPlate t={t}/>}
    {t >= 155.75 && t < 162.55 && <GameEquivalence t={t}/>}
    {t >= 174.75 && t < 182.5 && <ClosingEngraving t={t}/>}
  </>;
}
