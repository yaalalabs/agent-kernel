import React from 'react';
import clsx from 'clsx';
import styles from './styles.module.css';

/**
 * The three reading levels, drawn as three layers of one stack: the outcome on top, the code
 * in the middle, the runtime underneath. It is the picture for the home page level section,
 * and each persona page shows it with its own layer lit.
 *
 * Each layer is drawn flat in a 220 unit square and projected by one matrix, so the artwork
 * stays simple to edit. Colours and stroke match the stage drawings.
 */

const SIZE = 220;
const GAP = 150;
const CENTRE = 230;
const TOP = 34;
const COS = 0.866;
const SIN = 0.5;

/** Where a point on layer `level` lands on screen. */
const project = (x: number, y: number, level: number): [number, number] => [
  Math.round((CENTRE + COS * (x - y)) * 100) / 100,
  Math.round((TOP + level * GAP + SIN * (x + y)) * 100) / 100,
];

const matrix = (level: number): string => `matrix(${COS} ${SIN} ${-COS} ${SIN} ${CENTRE} ${TOP + level * GAP})`;

/* ---- What is drawn on each layer ------------------------------------------ */

/** The outcome: a few large tiles and one rising line. */
function Outcome(): JSX.Element {
  return (
    <>
      <rect className={styles.shape} x={24} y={24} width={172} height={76} rx={8} />
      <polyline className={styles.accent} points="40,84 76,66 104,72 140,48 180,36" />
      <rect className={styles.shape} x={24} y={116} width={78} height={80} rx={8} />
      <circle className={styles.shape} cx={63} cy={156} r={16} />
      <rect className={styles.shape} x={118} y={116} width={78} height={80} rx={8} />
      <line className={styles.shape} x1={134} y1={144} x2={180} y2={144} />
      <line className={styles.shape} x1={134} y1={166} x2={166} y2={166} />
    </>
  );
}

const CODE_LINES: Array<[indent: number, end: number, accent?: boolean]> = [
  [28, 124],
  [48, 176],
  [48, 146, true],
  [68, 190],
  [48, 112],
  [28, 86],
  [28, 150],
];

/** The code: a file, one line of it lit. */
function Code(): JSX.Element {
  return (
    <>
      {[30, 44, 58].map((x) => (
        <circle key={x} className={styles.shape} cx={x} cy={24} r={3.5} />
      ))}
      {CODE_LINES.map(([indent, end, accent], row) => (
        <line key={row} className={accent ? styles.accent : styles.shape} x1={indent} y1={52 + row * 22} x2={end} y2={52 + row * 22} />
      ))}
    </>
  );
}

const GRID = [36, 73, 110, 147, 184];
const BUSY = new Set(['1-1', '3-0', '2-3', '4-2', '0-4']);

/** The runtime: a lattice of workers, some of them busy, one in the accent. */
function Runtime(): JSX.Element {
  return (
    <>
      {GRID.map((at) => (
        <React.Fragment key={at}>
          <line className={styles.faint} x1={GRID[0]} y1={at} x2={GRID[4]} y2={at} />
          <line className={styles.faint} x1={at} y1={GRID[0]} x2={at} y2={GRID[4]} />
        </React.Fragment>
      ))}
      {GRID.map((y, row) =>
        GRID.map((x, column) => {
          const centre = row === 2 && column === 2;
          const busy = BUSY.has(`${column}-${row}`);
          return <circle key={`${x}-${y}`} className={centre ? styles.nodeAccent : busy ? styles.nodeBusy : styles.node} cx={x} cy={y} r={5.5} />;
        }),
      )}
    </>
  );
}

const LAYERS = [Outcome, Code, Runtime];

// Rails that tie one layer to the next, at the two outer corners, so they never cross a layer.
// Dots travel down them.
const DROPS: Array<[number, number]> = [
  [0, SIZE],
  [SIZE, 0],
];

export type LevelStackProps = {
  /** The layer to light: 0 is the top. Null lights none. */
  active?: number | null;
  /** Called when the pointer enters a layer, so a list beside the drawing can follow it. */
  onActivate?: (level: number) => void;
  className?: string;
};

export default function LevelStack({ active = null, onActivate, className }: LevelStackProps): JSX.Element {
  return (
    <svg className={clsx(styles.root, className)} viewBox="0 0 460 590" aria-hidden="true" focusable="false">
      {/* Painted from the bottom layer up, so each layer covers the ties that run under it */}
      {[2, 1, 0].map((level) => {
        const Drawing = LAYERS[level];
        const [labelX, labelY] = project(0, SIZE, level);
        return (
          <React.Fragment key={level}>
            {level < 2 && (
              <g>
                {DROPS.map(([x, y], i) => {
                  const [sx, sy] = project(x, y, level);
                  return (
                    <React.Fragment key={`${x}-${y}`}>
                      <line className={styles.rail} x1={sx} y1={sy} x2={sx} y2={sy + GAP} />
                      <circle className={styles.drop} cx={sx} cy={sy} r={3.5} style={{ animationDelay: `${-(level * 0.9 + i * 1.3)}s` }} />
                    </React.Fragment>
                  );
                })}
              </g>
            )}
            <g className={clsx(styles.layer, active === level && styles.layerActive)} onPointerEnter={onActivate ? () => onActivate(level) : undefined}>
              <g transform={matrix(level)}>
                <rect className={styles.plane} width={SIZE} height={SIZE} rx={10} />
                <Drawing />
              </g>
              <text className={styles.index} x={labelX - 12} y={labelY + 4} textAnchor="end">
                {`0${level + 1}`}
              </text>
            </g>
          </React.Fragment>
        );
      })}
    </svg>
  );
}
