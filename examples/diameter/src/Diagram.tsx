import {Easing, Interactive, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

const arc = [30, 70, 114, 152, 128, 96, 49, 26, 58, 110, 150, 120, 77, 37, 64, 103];
const ease = Easing.bezier(0.42, 0, 0.35, 1);

export function Diagram({progress}: {progress?: number}) {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const u = progress ?? (arc.length - 1) * frame / Math.max(1, durationInFrames - 1);
  const beat = Math.min(Math.floor(u), arc.length - 2);
  const angle = interpolate(u - beat, [0, 1], [arc[beat], arc[beat + 1]], {easing: ease});
  const radians = angle * Math.PI / 180;
  const radius = 365;
  const x = 546 + radius * Math.cos(radians);
  const y = 590 - radius * Math.sin(radians);
  const ax = 546 - radius;
  const bx = 546 + radius;
  const lengthA = Math.hypot(ax - x, 590 - y);
  const lengthB = Math.hypot(bx - x, 590 - y);
  const uX = (ax - x) * 44 / lengthA;
  const uY = (590 - y) * 44 / lengthA;
  const vX = (bx - x) * 44 / lengthB;
  const vY = (590 - y) * 44 / lengthB;

  return <Interactive.Svg name="圆与三角形" width="100%" height="100%" viewBox="0 0 1092 1146">
    <circle cx={546} cy={590} r={radius} fill="none" stroke="#342e25" strokeWidth={96}/>
    <circle cx={546} cy={590} r={radius} fill="none" stroke="#92764d" strokeWidth={4}/>
    <line x1={ax} y1={590} x2={bx} y2={590} stroke="#dabc80" strokeWidth={5}/>
    <polygon points={`${ax},590 ${x},${y} ${bx},590`}
      fill="#559baf" fillOpacity={0.12} stroke="#90b7c5" strokeWidth={5}/>
    <line x1={546} y1={590} x2={x} y2={y} stroke="#b18b53" strokeWidth={3} strokeDasharray="9 12"/>
    <polyline points={`${x+uX},${y+uY} ${x+uX+vX},${y+uY+vY} ${x+vX},${y+vY}`}
      fill="none" stroke="#f2d186" strokeWidth={5}/>
    <circle cx={546} cy={590} r={8} fill="#e3c997"/>
    <circle cx={x} cy={y} r={12} fill="#fff1d2"/>
  </Interactive.Svg>;
}
