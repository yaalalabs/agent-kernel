import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import useIsomorphicLayoutEffect from '@docusaurus/useIsomorphicLayoutEffect';
import clsx from 'clsx';
import styles from './styles.module.css';

/**
 * Line-art animations for the six stages of the runtime, in one vocabulary: particles on rails.
 * Rails are fine straight and angled lines, dots are requests, and a few plain outlines stand
 * for the parts of the runtime. Each drawing is a small machine that shows what its stage does.
 *
 * A drawing is data: routes (geometry) and tracks (keyframes over one loop). The same data
 * renders the static frame and drives the SMIL animation, so the frame that reduced-motion
 * users see, and that everyone sees before the page hydrates, is a real moment of the loop.
 */

export type Stage = 'build' | 'connect' | 'remember' | 'guard' | 'scale' | 'observe';

// The two halves of the Open Agent Kernel mark (branding/logo-mark, viewBox 0 0 86.86 86.85).
const MARK_LEFT =
  'M19.74,39.48v15.79l12.48,5.06c4.39,1.76,7.26,6.01,7.26,10.73v15.79l-27.78-11.11c-7.07-2.83-11.7-9.67-11.7-17.27V0l27.79,11.11c7.06,2.83,11.69,9.67,11.69,17.27v19.07L19.74,39.48Z';
const MARK_RIGHT =
  'M86.86,0v58.47c0,7.6-4.64,14.44-11.7,17.27l-27.78,11.11v-23.69c0-4.72,2.87-8.97,7.26-10.73l12.48-5.06v-15.79l-19.74,7.97v-11.17c0-7.6,4.63-14.44,11.69-17.27L86.86,0Z';
const MARK_SIZE = 86.86;

// Every drawing shares this frame: a 480 by 320 viewBox, ports on the left and right margins,
// and rails laid out about the centre line.
const VIEW_BOX = '0 0 480 320';
const LEFT = 40;
const RIGHT = 440;
const MID = 160;
const STROKE = 1.25; // the stroke width set in the stylesheet
const DOT = 3; // the radius of a dot

const round = (value: number): number => Math.round(value * 1e4) / 1e4;
const mod = (value: number, by: number): number => ((value % by) + by) % by;

/* ---- Geometry: routes ---------------------------------------------------- */

type Point = readonly [x: number, y: number];
/** A turn about a centre, in degrees. Positive is clockwise on screen. */
type Arc = { around: Point; sweep: number };

/** A path for rails and dots: straight stretches, and arcs of a circle for the ring. */
class Route {
  readonly d: string;
  readonly length: number;
  private readonly stretches: Array<{ length: number; at: (distance: number) => Point }> = [];

  constructor(start: Point, ...steps: Array<Point | Arc>) {
    let here = start;
    let d = `M${round(start[0])},${round(start[1])}`;
    for (const step of steps) {
      if ('around' in step) {
        const [cx, cy] = step.around;
        const radius = Math.hypot(here[0] - cx, here[1] - cy);
        const from = Math.atan2(here[1] - cy, here[0] - cx);
        const sweep = (step.sweep * Math.PI) / 180;
        const on = (angle: number): Point => [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
        // An SVG arc is ambiguous past half a turn, so it is written in quarter turns or less.
        const pieces = Math.ceil(Math.abs(step.sweep) / 90);
        for (let i = 1; i <= pieces; i++) {
          const [x, y] = on(from + (sweep * i) / pieces);
          d += `A${round(radius)},${round(radius)} 0 0 ${sweep > 0 ? 1 : 0} ${round(x)},${round(y)}`;
        }
        this.stretches.push({ length: Math.abs(sweep) * radius, at: (s) => on(from + (Math.sign(sweep) * s) / radius) });
        here = on(from + sweep);
      } else {
        const [x0, y0] = here;
        const [x1, y1] = step;
        const length = Math.hypot(x1 - x0, y1 - y0);
        if (length === 0) continue;
        d += `L${round(x1)},${round(y1)}`;
        this.stretches.push({ length, at: (s) => [x0 + ((x1 - x0) * s) / length, y0 + ((y1 - y0) * s) / length] });
        here = step;
      }
    }
    this.d = d;
    this.length = this.stretches.reduce((sum, stretch) => sum + stretch.length, 0);
  }

  /** The point at a distance along the route. */
  at(distance: number): Point {
    let left = Math.max(0, Math.min(distance, this.length));
    for (const stretch of this.stretches) {
      if (left <= stretch.length) return stretch.at(left);
      left -= stretch.length;
    }
    // Rounding can leave a hair of distance after the last stretch: that is the end of the route.
    const last = this.stretches[this.stretches.length - 1];
    return last.at(last.length);
  }
}

/* ---- Time: tracks -------------------------------------------------------- */

type Ease = 'in' | 'out' | 'inOut';
/** A keyframe: time in seconds, value, and the easing of the stretch that ends at it. */
type Key = readonly [time: number, value: number, ease?: Ease];
/** Keyframes in time order, within one loop. The value holds before the first and after the last. */
type Track = readonly Key[];

// `in` leaves rest and reaches twice its average speed; `out` is the reverse. A stretch eased
// this way, and given twice the time, joins a constant-speed stretch with no jump in speed.
const SPLINES: Record<Ease | 'linear', readonly [number, number, number, number]> = {
  linear: [0, 0, 1, 1],
  in: [0.4, 0, 0.7, 0.4],
  out: [0.3, 0.6, 0.6, 1],
  inOut: [0.45, 0, 0.25, 1],
};

/** A cubic bezier easing curve, read at a time fraction. */
function eased(ease: Ease, fraction: number): number {
  const [x1, y1, x2, y2] = SPLINES[ease];
  const curve = (a: number, b: number, u: number) => 3 * a * u * (1 - u) ** 2 + 3 * b * u * u * (1 - u) + u ** 3;
  let low = 0;
  let high = 1;
  for (let i = 0; i < 24; i++) {
    const middle = (low + high) / 2;
    if (curve(x1, x2, middle) < fraction) low = middle;
    else high = middle;
  }
  return curve(y1, y2, (low + high) / 2);
}

/** The value of a track at a time: this is what the static frame is drawn from. */
function valueAt(track: Track, time: number): number {
  if (time <= track[0][0]) return track[0][1];
  for (let i = 1; i < track.length; i++) {
    const [t1, v1, ease] = track[i];
    if (time <= t1) {
      const [t0, v0] = track[i - 1];
      const fraction = t1 === t0 ? 1 : (time - t0) / (t1 - t0);
      return v0 + (v1 - v0) * (ease ? eased(ease, fraction) : fraction);
    }
  }
  return track[track.length - 1][1];
}

const endOf = (track: Track): number => track[track.length - 1][0];

const EASE_LENGTH = 28; // how far a dot travels while it eases to or from rest

/**
 * Keys for a run along a route at a constant speed, starting at `start` seconds. `launch`
 * eases away from rest and `settle` eases to rest, so a dot can stop and go without a jolt.
 */
function run(
  route: Route,
  start: number,
  speed: number,
  { from = 0, to = route.length, launch = false, settle = false }: { from?: number; to?: number; launch?: boolean; settle?: boolean } = {},
): Key[] {
  const ramp = Math.min(EASE_LENGTH, (to - from) / 2);
  const keys: Key[] = [[start, from / route.length]];
  let time = start;
  let distance = from;
  if (launch) {
    time += (2 * ramp) / speed;
    distance += ramp;
    keys.push([time, distance / route.length, 'in']);
  }
  const cruiseTo = settle ? to - ramp : to;
  time += (cruiseTo - distance) / speed;
  keys.push([time, cruiseTo / route.length]);
  if (settle) keys.push([time + (2 * ramp) / speed, to / route.length, 'out']);
  return keys;
}

/** Opacity keys: fade in from `from`, stay, and fade out by `to`. */
function shown(from: number, to: number, fade = 0.35): Key[] {
  return [[from, 0], [from + fade, 1], [to - fade, 1], [to, 0]];
}

/** A dot that fades in, crosses a whole route at a constant speed, and fades out. */
function crossing(route: Route, speed: number, fade?: number): { route: Route; move: Track; show: Track } {
  const move = run(route, 0, speed);
  return { route, move, show: shown(0, endOf(move), fade) };
}

/* ---- The clock, and the three primitives: rail, dot, pulse ---------------- */

/** One loop of a drawing: its length, the moment the static frame shows, and whether it runs. */
type Clock = { loop: number; rest: number; live: boolean };
const ClockContext = createContext<Clock>({ loop: 8, rest: 0, live: false });

/** A track as SMIL attributes. `at` is the moment in the loop at which the track's time starts. */
function smil(track: Track, clock: Clock, at: number, map: (value: number) => number = (value) => value) {
  const keys: Key[] = [...track];
  if (keys[0][0] > 0) keys.unshift([0, keys[0][1]]);
  const last = keys[keys.length - 1];
  if (last[0] < clock.loop) keys.push([clock.loop, last[1]]);
  const curved = keys.some((key) => key[2]);
  return {
    dur: `${clock.loop}s`,
    begin: `${round(at - clock.loop)}s`,
    repeatCount: 'indefinite',
    calcMode: curved ? 'spline' : 'linear',
    keyTimes: keys.map((key) => round(Math.min(1, key[0] / clock.loop))).join(';'),
    keySplines: curved ? keys.slice(1).map((key) => SPLINES[key[2] ?? 'linear'].join(' ')).join(';') : undefined,
    values: keys.map((key) => round(map(key[1]))).join(';'),
  };
}

/** The static opacity of an element, from its track at the rest moment. */
function restOpacity(show: Track | undefined, clock: Clock, at: number): number | undefined {
  return show ? round(valueAt(show, mod(clock.rest - at, clock.loop))) : undefined;
}

/** Rail: one or more fixed lines. Routes given together are stroked as one shape. */
function Rail({ via, faint }: { via: Route | Route[]; faint?: boolean }): JSX.Element {
  const routes = Array.isArray(via) ? via : [via];
  return <path className={faint ? styles.faint : styles.rail} d={routes.map((route) => route.d).join('')} />;
}

/** Port: the open end of a rail, where dots enter or leave. */
function Port({ at }: { at: Point }): JSX.Element {
  return <circle className={styles.port} cx={at[0]} cy={at[1]} r={3} />;
}

type Timed = {
  /** Opacity over the loop. Left out, the element is always shown. */
  show?: Track;
  /** The moment in the loop at which this element's tracks start. */
  at?: number;
};

/** Shown: fixed artwork that fades in and out on a track. */
function Shown({ show, at = 0, children }: Timed & { children: React.ReactNode }): JSX.Element {
  const clock = useContext(ClockContext);
  return (
    <g opacity={clock.live ? undefined : restOpacity(show, clock, at)}>
      {clock.live && show && <animate attributeName="opacity" {...smil(show, clock, at)} />}
      {children}
    </g>
  );
}

/** Mover: carries its children along a route. `move` is the fraction of the route covered. */
function Mover({ route, move, show, at = 0, children }: Timed & { route: Route; move: Track; children: React.ReactNode }): JSX.Element {
  const clock = useContext(ClockContext);
  if (!clock.live) {
    const [x, y] = route.at(valueAt(move, mod(clock.rest - at, clock.loop)) * route.length);
    return (
      <g transform={`translate(${round(x)} ${round(y)})`} opacity={restOpacity(show, clock, at)}>
        {children}
      </g>
    );
  }
  const { values, ...timing } = smil(move, clock, at);
  return (
    <g>
      <animateMotion path={route.d} keyPoints={values} {...timing} />
      {show && <animate attributeName="opacity" {...smil(show, clock, at)} />}
      {children}
    </g>
  );
}

/** Dot: a request travelling along a route. */
function Dot(mover: Timed & { route: Route; move: Track }): JSX.Element {
  return (
    <Mover {...mover}>
      <circle className={styles.dot} r={DOT} />
    </Mover>
  );
}

/**
 * Pulse: a stretch of rail that draws itself along its length, and can draw back again.
 * It is a line that travels, not a flash. `draw` is the fraction of the stretch drawn.
 */
function Pulse({ route, draw, show, at = 0 }: Timed & { route: Route; draw: Track }): JSX.Element {
  const clock = useContext(ClockContext);
  const offset = (drawn: number) => 1 - drawn;
  return (
    <path
      className={styles.rail}
      d={route.d}
      pathLength={1}
      strokeDasharray="1 2"
      strokeDashoffset={round(offset(valueAt(draw, mod(clock.rest - at, clock.loop))))}
      opacity={clock.live ? undefined : restOpacity(show, clock, at)}
    >
      {clock.live && <animate attributeName="stroke-dashoffset" {...smil(draw, clock, at, offset)} />}
      {clock.live && show && <animate attributeName="opacity" {...smil(show, clock, at)} />}
    </path>
  );
}

/* ---- Build ---------------------------------------------------------------- */

const BUILD = (() => {
  const loop = 8;
  const rest = 6.4; // all four are in, and a dot is on its way out
  const cellX = 334;
  const cellY = [94, 138, 182, 226];
  const startY = [64, 128, 192, 256];
  const bend = 236; // where each rail has turned onto the level of its cell
  const agents = cellY.map((y, i) => {
    const route = new Route([LEFT, startY[i]], [bend - Math.abs(y - startY[i]), startY[i]], [bend, y], [cellX, y]);
    const leave = 0.8 + i * 0.5;
    // Each outline appears beside its port, then slides down the rail into its cell.
    const move: Track = [[leave, 28 / route.length], [leave + 2.8, 1, 'inOut']];
    const show: Track = [[0.2 + i * 0.15, 0], [0.6 + i * 0.15, 1], [7.1, 1], [7.6, 0]];
    return { route, move, show };
  });
  const out = new Route([cellX + 30, MID], [RIGHT, MID]); // from the right edge of the frame
  const served = [5.5, 6.2].map((at) => ({ at, ...crossing(out, 60, 0.25) }));
  return { loop, rest, cellX, cellY, startY, agents, out, served };
})();

// Four outlines, one per framework, each drawn about its own centre.
const AGENT_OUTLINES = [
  <circle className={styles.outline} r={11} />,
  <polygon className={styles.outline} points="0,-11.5 12,9 -12,9" />,
  <rect className={styles.outline} x={-10} y={-10} width={20} height={20} rx={2} />,
  <polygon className={styles.outline} points="12,0 6,10.4 -6,10.4 -12,0 -6,-10.4 6,-10.4" />,
];

/**
 * Build: agents written in different frameworks are differently shaped outlines. Each travels
 * down its own rail and slots into a cell of one common frame (the accent). Once all four are
 * in, dots leave on the single rail out: one runtime serves them all.
 */
function Build(): JSX.Element {
  return (
    <>
      <Rail via={[...BUILD.agents.map((agent) => agent.route), BUILD.out]} />
      {BUILD.startY.map((y) => (
        <Port key={y} at={[LEFT, y]} />
      ))}
      <Port at={[RIGHT, MID]} />
      {BUILD.served.map((dot) => (
        <Dot key={dot.at} {...dot} />
      ))}
      <rect className={styles.accentKnock} x={BUILD.cellX - 30} y={64} width={60} height={192} rx={10} />
      {BUILD.cellY.map((y) => (
        <rect key={y} className={styles.faint} x={BUILD.cellX - 18} y={y - 18} width={36} height={36} rx={6} />
      ))}
      {BUILD.agents.map((agent, i) => (
        <Mover key={i} {...agent}>
          {AGENT_OUTLINES[i]}
        </Mover>
      ))}
    </>
  );
}

/* ---- Connect -------------------------------------------------------------- */

const CONNECT = (() => {
  const loop = 8;
  const rest = 3; // a dot is in the node, others are on their way in and out
  const speed = 90;
  const rows = [64, 112, 160, 208, 256];
  const node: Point = [240, MID];
  // A rail runs level from its port, then turns at 45 degrees onto the node.
  const turn = (y: number, side: 1 | -1): Point => [node[0] + side * Math.abs(y - MID), y];
  const inbound = rows.map((y) => new Route([LEFT, y], turn(y, -1), node));
  const outbound = rows.map((y) => new Route(node, turn(y, 1), [RIGHT, y]));
  // Which entry each dot comes from and which exit it takes. One dot reaches the node a second.
  const pairs = [[0, 2], [3, 0], [1, 4], [4, 1], [2, 3], [0, 4], [3, 2], [1, 0]];
  const dots = pairs.map(([entry, exit], i) => {
    const route = new Route([LEFT, rows[entry]], turn(rows[entry], -1), node, turn(rows[exit], 1), [RIGHT, rows[exit]]);
    return { ...crossing(route, speed), at: mod(i - inbound[entry].length / speed, loop) };
  });
  return { loop, rest, rows, node, inbound, outbound, dots };
})();

/**
 * Connect: requests arrive from five entry points on the left, every one passes through the
 * same node (the accent), and they fan out to five exits on the right.
 */
function Connect(): JSX.Element {
  return (
    <>
      <Rail via={[...CONNECT.inbound, ...CONNECT.outbound]} />
      {CONNECT.rows.map((y) => (
        <React.Fragment key={y}>
          <Port at={[LEFT, y]} />
          <Port at={[RIGHT, y]} />
        </React.Fragment>
      ))}
      <circle className={styles.accentKnock} cx={CONNECT.node[0]} cy={CONNECT.node[1]} r={14} />
      {CONNECT.dots.map((dot, i) => (
        <Dot key={i} {...dot} />
      ))}
    </>
  );
}

/* ---- Remember ------------------------------------------------------------- */

const REMEMBER = (() => {
  const loop = 10;
  const rest = 6.8; // the ring is full, and four dots are passing
  const speed = 110;
  const centre: Point = [240, MID];
  const radius = 72;
  const railY = MID + radius; // the rail touches the foot of the ring
  const rail = new Route([LEFT, railY], [RIGHT, railY]);
  // Where each kept dot comes to rest, in degrees round the ring from the foot. The first dot
  // goes furthest, so the ones behind it never have to pass it.
  const slots = [310, 258, 206, 154, 102, 50];
  const kept = slots.map((turn, i) => {
    const at = i * 0.5;
    const route = new Route([LEFT, railY], [centre[0], railY], { around: centre, sweep: -turn });
    const move = run(route, 0, speed, { settle: true });
    const show: Track = [[0, 0], [0.3, 1], [9 - at, 1], [9.6 - at, 0]];
    return { at, route, move, show };
  });
  const passing = [3.5, 4.5, 5.5, 6.5, 7.5, 8.5].map((at) => ({ at, ...crossing(rail, speed) }));
  return { loop, rest, centre, radius, rail, railY, kept, passing };
})();

/**
 * Remember: six dots leave the rail where it touches the ring (the accent), travel round it
 * and settle one behind another. They stay there while later dots pass along the rail.
 */
function Remember(): JSX.Element {
  return (
    <>
      <Rail via={REMEMBER.rail} />
      <circle className={styles.accent} cx={REMEMBER.centre[0]} cy={REMEMBER.centre[1]} r={REMEMBER.radius} />
      <Port at={[LEFT, REMEMBER.railY]} />
      <Port at={[RIGHT, REMEMBER.railY]} />
      {REMEMBER.passing.map((dot) => (
        <Dot key={dot.at} {...dot} />
      ))}
      {REMEMBER.kept.map((dot) => (
        <Dot key={dot.at} {...dot} />
      ))}
    </>
  );
}

/* ---- Guard ---------------------------------------------------------------- */

const GUARD = (() => {
  const loop = 9;
  const rest = 3.9; // one dot has crossed, one is arriving, one is on its way back
  const speed = 90;
  const scale = 1.5;
  const width = MARK_SIZE * scale;
  const mark = { x: 240 - width / 2, y: MID - width / 2, scale, right: 240 + width / 2 };
  const through = new Route([LEFT, MID], [RIGHT, MID]);
  // A refused dot stops just short of the boundary, then leaves by the lower rail, back the way it came.
  const stop = mark.x - 5 - LEFT;
  const lower = MID + 48;
  const back = new Route([LEFT, MID], [LEFT + stop, MID], [LEFT + stop - 48, lower], [LEFT, lower]);
  const refused = [1, 4];
  const dots = Array.from({ length: 7 }, (_, i) => {
    const at = (i * loop) / 7;
    if (!refused.includes(i)) return { at, ...crossing(through, speed) };
    const arrive = run(back, 0, speed, { to: stop, settle: true });
    const leave = run(back, endOf(arrive) + 0.15, speed, { from: stop, launch: true });
    const move = [...arrive, ...leave];
    return { at, route: back, move, show: shown(0, endOf(move)) };
  });
  const rails = [
    new Route([LEFT, MID], [mark.x, MID]),
    new Route([mark.right, MID], [RIGHT, MID]),
    new Route([LEFT + stop, MID], [LEFT + stop - 48, lower], [LEFT, lower]),
  ];
  return { loop, rest, mark, lower, rails, dots };
})();

/**
 * Guard: dots travel along a rail to a boundary drawn from the outline of the OAK mark (the
 * accent). Most cross it and carry on to the exit. Two in every seven stop at its edge and
 * are turned back along the lower rail.
 */
function Guard(): JSX.Element {
  const { mark } = GUARD;
  return (
    <>
      <Rail via={GUARD.rails} />
      <Port at={[LEFT, MID]} />
      <Port at={[LEFT, GUARD.lower]} />
      <Port at={[RIGHT, MID]} />
      <g transform={`translate(${round(mark.x)} ${round(mark.y)}) scale(${mark.scale})`}>
        <path className={styles.accent} style={{ strokeWidth: STROKE / mark.scale }} d={MARK_LEFT} />
        <path className={styles.accent} style={{ strokeWidth: STROKE / mark.scale }} d={MARK_RIGHT} />
      </g>
      {GUARD.dots.map((dot) => (
        <Dot key={dot.at} {...dot} />
      ))}
    </>
  );
}

/* ---- Scale ---------------------------------------------------------------- */

const SCALE = (() => {
  const loop = 10;
  const rest = 4.95; // every lane is open, and the queue is half drained
  const speed = 110;
  const split: Point = [184, MID];
  const laneY = [96, 128, 160, 192, 224];
  const corner = (y: number): Point => [split[0] + Math.abs(y - MID), y];
  // The whole way for a dot: entry, split, a 45 degree turn onto its lane, exit.
  const ways = laneY.map((y) => new Route([LEFT, MID], split, corner(y), [RIGHT, y]));

  // The four lanes that open. An outer lane branches from the corner of the inner one beside it.
  const inner = [1, 3].map((i) => ({
    y: laneY[i],
    route: new Route(split, corner(laneY[i]), [RIGHT, laneY[i]]),
    draw: [[3, 0], [3.9, 1, 'inOut'], [9, 1], [9.7, 0, 'inOut']] as Track,
    show: [[2.95, 0], [3.05, 1], [9.7, 1], [9.8, 0]] as Track,
    port: [[3.7, 0], [3.9, 1], [9, 1], [9.15, 0]] as Track,
  }));
  const outer = [0, 4].map((i) => ({
    y: laneY[i],
    route: new Route(corner(laneY[i === 0 ? 1 : 3]), corner(laneY[i]), [RIGHT, laneY[i]]),
    draw: [[3.3, 0], [4.2, 1, 'inOut'], [8.8, 1], [9.4, 0, 'inOut']] as Track,
    show: [[3.25, 0], [3.35, 1], [9.4, 1], [9.5, 0]] as Track,
    port: [[4, 0], [4.2, 1], [8.8, 1], [8.95, 0]] as Track,
  }));

  // The first dot has the one lane to itself. The seven behind it queue before the split, and
  // once the lanes have opened they leave in turn, each for a different lane.
  const leader = { at: 0, ...crossing(ways[2], speed) };
  const queued = [2, 1, 3, 0, 4, 2, 1].map((lane, place) => {
    const at = 0.3 * (place + 1);
    const route = ways[lane];
    const slot = 124 - 10 * place; // distance from the entry to this place in the queue
    const arrive = run(route, 0, speed, { to: slot, settle: true });
    const leave = run(route, 3.6 + 0.3 * place - at, speed, { from: slot, launch: true });
    const move = [...arrive, ...leave];
    return { at, route, move, show: shown(0, endOf(move)) };
  });
  return { loop, rest, split, single: ways[2], lanes: [...inner, ...outer], dots: [leader, ...queued] };
})();

/**
 * Scale: one lane carries one dot at a time, so a queue forms before the split (the accent).
 * Four more lanes draw out from the split, and the queue drains into all five side by side.
 * When it is empty the extra lanes draw back.
 */
function Scale(): JSX.Element {
  const [x, y] = SCALE.split;
  return (
    <>
      <Rail via={SCALE.single} />
      {SCALE.lanes.map((lane) => (
        <React.Fragment key={lane.y}>
          <Pulse route={lane.route} draw={lane.draw} show={lane.show} />
          <Shown show={lane.port}>
            <Port at={[RIGHT, lane.y]} />
          </Shown>
        </React.Fragment>
      ))}
      <Port at={[LEFT, MID]} />
      <Port at={[RIGHT, MID]} />
      <path className={styles.accentKnock} d={`M${x - 8},${y}L${x},${y - 8}L${x + 8},${y}L${x},${y + 8}Z`} />
      {SCALE.dots.map((dot) => (
        <Dot key={dot.at} {...dot} />
      ))}
    </>
  );
}

/* ---- Observe -------------------------------------------------------------- */

const OBSERVE = (() => {
  const loop = 8;
  const rest = 5.1; // the marker is most of the way across, and the last span has begun
  const top = 64;
  const rows = [96, 128, 160, 192, 224, 256];
  const sweep = { from: 0.3, to: 5.9 }; // when the marker leaves the left edge and reaches the right
  // The moment the marker is at x. A span draws exactly as fast as the marker moves over it.
  const when = (x: number) => sweep.from + ((x - LEFT) / (RIGHT - LEFT)) * (sweep.to - sweep.from);
  const fadeOut: Key[] = [[6.9, 1], [7.5, 0]];
  // One span per row. `parent` is the row of the span it is nested in.
  const spans = [
    { from: 40, to: 440, parent: -1 },
    { from: 64, to: 208, parent: 0 },
    { from: 88, to: 168, parent: 1 },
    { from: 232, to: 416, parent: 0 },
    { from: 256, to: 344, parent: 3 },
    { from: 360, to: 416, parent: 3 },
  ].map((span, row) => {
    const y = rows[row];
    const starts = when(span.from);
    return {
      start: [span.from, y] as Point,
      line: new Route([span.from, y], [span.to, y]),
      draw: [[starts, 0], [when(span.to), 1]] as Track,
      show: [[Math.max(0, starts - 0.1), 0], [starts + 0.05, 1], ...fadeOut] as Track,
      // The link drops from the parent span to the start of this one. The marker uncovers it.
      link: span.parent < 0 ? null : new Route([span.from, rows[span.parent]], [span.from, y]),
    };
  });
  // The ruler the marker rides: a level rail with a tick every 40 units.
  const ticks = Array.from({ length: 11 }, (_, i) => new Route([LEFT + i * 40, top - 5], [LEFT + i * 40, top]));
  const marker = {
    route: new Route([LEFT, top], [RIGHT, top]),
    move: [[sweep.from, 0], [sweep.to, 1]] as Track,
    show: [[0, 0], [0.3, 1], [6.8, 1], [7.3, 0]] as Track,
    drop: rows[rows.length - 1] + 12 - top,
  };
  return { loop, rest, spans, marker, ticks };
})();

/**
 * Observe: a trace draws across as a waterfall of nested spans, each starting under its
 * parent. The marker (the accent) rides the ruler at the top and scans the trace as it is recorded.
 */
function Observe(): JSX.Element {
  const { spans, marker, ticks } = OBSERVE;
  return (
    <>
      <Rail faint via={[marker.route, ...ticks]} />
      {spans.map((span, row) => (
        <React.Fragment key={row}>
          <Pulse route={span.line} draw={span.draw} show={span.show} />
          <Shown show={span.show}>
            {span.link && <Rail faint via={span.link} />}
            <circle className={styles.dot} cx={span.start[0]} cy={span.start[1]} r={DOT} />
          </Shown>
        </React.Fragment>
      ))}
      <Mover route={marker.route} move={marker.move} show={marker.show}>
        <line className={styles.accent} x1={0} y1={0} x2={0} y2={marker.drop} />
        <circle className={styles.dotAccent} r={DOT} />
      </Mover>
    </>
  );
}

/* ---- The component -------------------------------------------------------- */

// For each stage: the loop length in seconds, the moment of the loop that is the static
// frame, and the drawing.
const STAGES: Record<Stage, { loop: number; rest: number; Drawing: () => JSX.Element }> = {
  build: { loop: BUILD.loop, rest: BUILD.rest, Drawing: Build },
  connect: { loop: CONNECT.loop, rest: CONNECT.rest, Drawing: Connect },
  remember: { loop: REMEMBER.loop, rest: REMEMBER.rest, Drawing: Remember },
  guard: { loop: GUARD.loop, rest: GUARD.rest, Drawing: Guard },
  scale: { loop: SCALE.loop, rest: SCALE.rest, Drawing: Scale },
  observe: { loop: OBSERVE.loop, rest: OBSERVE.rest, Drawing: Observe },
};

/**
 * Decides whether the drawing runs, and keeps it paused while nobody can see it.
 * The server render and the first client render are the static frame. Motion starts after
 * mount, only if the visitor has not asked for reduced motion, and carries on from that frame.
 */
function useLiveMotion(svg: React.RefObject<SVGSVGElement>, stage: Stage, rest: number): boolean {
  const [live, setLive] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setLive(!reduced.matches);
    update();
    reduced.addEventListener('change', update);
    return () => reduced.removeEventListener('change', update);
  }, []);

  // Before the first moving frame is painted, set the loop to the moment of the static frame.
  useIsomorphicLayoutEffect(() => {
    if (live) svg.current?.setCurrentTime(rest);
  }, [svg, live, stage, rest]);

  useEffect(() => {
    const element = svg.current;
    if (!element || !live) return undefined;
    let onScreen = true;
    const sync = () => {
      const running = onScreen && !document.hidden;
      // SMIL is paused on the element. The attribute pauses CSS animations (see the stylesheet).
      if (running) element.unpauseAnimations();
      else element.pauseAnimations();
      element.toggleAttribute('data-paused', !running);
    };
    const seen = new IntersectionObserver(([entry]) => {
      onScreen = entry.isIntersecting;
      sync();
    });
    seen.observe(element);
    document.addEventListener('visibilitychange', sync);
    return () => {
      seen.disconnect();
      document.removeEventListener('visibilitychange', sync);
      element.unpauseAnimations();
      element.removeAttribute('data-paused');
    };
  }, [svg, live, stage]);

  return live;
}

/** The line-art animation for one stage of the runtime. Decorative: hidden from assistive technology. */
export function StageMotion({ stage, className }: { stage: Stage; className?: string }): JSX.Element {
  const svg = useRef<SVGSVGElement>(null);
  const { loop, rest, Drawing } = STAGES[stage];
  const live = useLiveMotion(svg, stage, rest);
  const clock = useMemo(() => ({ loop, rest, live }), [loop, rest, live]);
  return (
    <svg ref={svg} className={clsx(styles.root, className)} viewBox={VIEW_BOX} data-stage={stage} aria-hidden="true" focusable="false">
      <ClockContext.Provider value={clock}>
        <Drawing />
      </ClockContext.Provider>
    </svg>
  );
}
