import {clamp, lerp, ramp, score, slide} from './stage';

export const heapX = [283, 500, 717];
export const stoneY = (index: number) => 1090 - 64 * index;
export const upperRailY = 654;
export const lowerRailY = 1271;

export type Move = typeof score.moves[number];
type Point = {x: number; y: number};
export const flightDuration = .78;
const bite = .22;
const travelStart = .17;
const rollStart = .205;
const rollEnd = rollStart + .26;

export const gameMovesAt = (t: number) => t < 34.8 ? score.moves.slice(0, 5) : score.moves.slice(5);

export function countMotionAt(t: number) {
  const moves = gameMovesAt(t);
  const last = moves.reduce<Move | undefined>((latest, move) => move.timeSec <= t ? move : latest, undefined);
  if (!last) return {before: moves[0].before, after: moves[0].before, progress: 1};
  const progress = ramp(t, last.timeSec + rollStart, last.timeSec + rollEnd);
  return {before: last.before, after: last.after, progress};
}

export function countAt(t: number) {
  const motion = countMotionAt(t);
  return motion.progress < .5 ? motion.before : motion.after;
}

const jitter = [-.94, 1.17, -.38, .69, -1.14, .25];
export function laidPosition(heap: number, index: number) {
  return {
    x: heapX[heap] + jitter[(index + heap * 2) % jitter.length],
    y: stoneY(index) + jitter[(index * 3 + heap) % jitter.length] * .65,
  };
}

const cubic = (a: Point, b: Point, c: Point, d: Point, u: number): Point => ({
  x: (1 - u) ** 3 * a.x + 3 * (1 - u) ** 2 * u * b.x + 3 * (1 - u) * u ** 2 * c.x + u ** 3 * d.x,
  y: (1 - u) ** 3 * a.y + 3 * (1 - u) ** 2 * u * b.y + 3 * (1 - u) * u ** 2 * c.y + u ** 3 * d.y,
});

export function flight(move: Move, index: number, t: number) {
  const heap = move.heap - 1;
  const origin = laidPosition(heap, index);
  const stackOrder = move.before[heap] - 1 - index;
  const offset = Math.min(.055, stackOrder * .014);
  const seconds = t - move.timeSec - offset;
  const act = clamp(seconds / flightDuration);
  const grip = ramp(seconds, 0, bite);
  const travel = slide(seconds, travelStart, flightDuration - offset);
  const up = move.player === 'first';
  const side = heap === 0 ? -1 : 1;
  const target = {x: (side < 0 ? 172 : 855) + side * stackOrder * 13, y: up ? upperRailY : lowerRailY};
  const begin = {x: origin.x, y: origin.y - 5 * grip};
  const controlA = {x: origin.x + side * (up ? 41 : 57), y: origin.y - (up ? 122 : 60)};
  const controlB = {x: target.x + side * (up ? 22 : 45), y: lerp(origin.y, target.y, up ? .44 : .52)};
  return {
    ...cubic(begin, controlA, controlB, target, travel), origin, target, grip, travel,
    active: act, lift: 5 * grip + 100 * travel,
    scale: lerp(1, .41, travel), opacity: 1 - slide(seconds, .60 - offset, flightDuration - offset),
  };
}
