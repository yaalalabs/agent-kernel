import React, { useEffect, useId, useRef, useState } from 'react';
import clsx from 'clsx';
import styles from './styles.module.css';

type OakMarkProps = {
  /** `hero` is the animated 3D scene; `hub` and `cta` are the flat mark with a glow. */
  variant?: 'hero' | 'hub' | 'cta';
  /** Set to false for a static mark. Reduced-motion users always get the static mark. */
  animated?: boolean;
  className?: string;
};

// The two halves of the Open Agent Kernel mark (branding/logo-mark, viewBox 0 0 86.86 86.85).
const LEFT =
  'M19.74,39.48v15.79l12.48,5.06c4.39,1.76,7.26,6.01,7.26,10.73v15.79l-27.78-11.11c-7.07-2.83-11.7-9.67-11.7-17.27V0l27.79,11.11c7.06,2.83,11.69,9.67,11.69,17.27v19.07L19.74,39.48Z';
const RIGHT =
  'M86.86,0v58.47c0,7.6-4.64,14.44-11.7,17.27l-27.78,11.11v-23.69c0-4.72,2.87-8.97,7.26-10.73l12.48-5.06v-15.79l-19.74,7.97v-11.17c0-7.6,4.63-14.44,11.69-17.27L86.86,0Z';
const VIEW_BOX = '0 0 86.86 86.85';

function useSafeId(prefix: string): string {
  return `${prefix}-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
}

/* ── Flat mark: diagram hubs and calls to action ─────────────────────────── */

function FlatMark({ variant, animated, className }: Required<Pick<OakMarkProps, 'variant' | 'animated'>> & { className?: string }): JSX.Element {
  const gradientId = useSafeId('oak-mark');
  return (
    <div className={clsx(styles.root, styles[variant], animated && styles.animated, className)} aria-hidden="true">
      <div className={styles.glow} />
      <svg className={styles.svg} viewBox="-4 -4 94.86 94.85" focusable="false">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--ak-primary)" />
            <stop offset="100%" stopColor="var(--ak-primary-soft)" />
          </linearGradient>
        </defs>
        <g className={styles.fill} fill={`url(#${gradientId})`}>
          <path d={LEFT} />
          <path d={RIGHT} />
        </g>
        <g className={styles.outline}>
          <path d={LEFT} pathLength={1} />
          <path d={RIGHT} pathLength={1} />
        </g>
      </svg>
    </div>
  );
}

/* ── Hero scene: the kernel in 3D with agents in orbit ───────────────────── */

const DEPTH = 14; // slices that make up the extruded body
const SLICE_PX = 2.2; // distance between slices

/** Shade for an extrusion slice: 0 is just behind the face, 1 is the back. */
function sideColour(t: number): string {
  const from = [214, 72, 34];
  const to = [112, 34, 14];
  const c = from.map((v, i) => Math.round(v + (to[i] - v) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

type Ring = { rx: number; ry: number; rotate: number };
const RINGS: Ring[] = [
  { rx: 186, ry: 52, rotate: -16 },
  { rx: 232, ry: 82, rotate: 12 },
  { rx: 270, ry: 110, rotate: -5 },
];

// Agents travelling the rings. `begin` is negative so they start spread out.
type Satellite = { ring: number; dur: number; begin: number; r: number; accent?: boolean };
const SATELLITES: Satellite[] = [
  { ring: 0, dur: 15, begin: -2, r: 6.5, accent: true },
  { ring: 1, dur: 23, begin: -9, r: 5 },
  { ring: 1, dur: 23, begin: -20, r: 3.5 },
  { ring: 2, dur: 33, begin: -6, r: 4.5 },
  { ring: 2, dur: 33, begin: -23, r: 6, accent: true },
];

// Fixed positions for the background specks, so server and client render the same scene.
const SPECKS: Array<[number, number, number, number]> = [
  [-232, -168, 1.6, 0], [-150, -236, 1.2, 1.4], [-40, -250, 1.8, 2.6], [96, -228, 1.3, 0.8],
  [206, -182, 1.7, 3.1], [252, -66, 1.2, 1.9], [240, 96, 1.6, 0.3], [150, 214, 1.3, 2.2],
  [18, 246, 1.7, 3.6], [-120, 226, 1.2, 1.1], [-222, 138, 1.6, 2.9], [-256, -24, 1.3, 0.6],
];

function ellipsePath({ rx, ry }: Ring): string {
  // Starts at the right, comes round the front (below the centre line), returns round the back.
  return `M${rx},0 A${rx},${ry} 0 1,1 ${-rx},0 A${rx},${ry} 0 1,1 ${rx},0`;
}

function OrbitLayer({ side, ids, moving }: { side: 'back' | 'front'; ids: { upper: string; lower: string }; moving: boolean }): JSX.Element {
  const clip = side === 'back' ? ids.upper : ids.lower;
  return (
    <svg className={clsx(styles.orbits, side === 'back' ? styles.orbitsBack : styles.orbitsFront)} viewBox="-300 -300 600 600" focusable="false">
      <defs>
        <clipPath id={ids.upper}>
          <rect x="-320" y="-320" width="640" height="320" />
        </clipPath>
        <clipPath id={ids.lower}>
          <rect x="-320" y="0" width="640" height="320" />
        </clipPath>
      </defs>
      {side === 'back' &&
        SPECKS.map(([x, y, r, delay]) => (
          <circle key={`${x}-${y}`} className={styles.speck} cx={x} cy={y} r={r} style={{ animationDelay: `${delay}s` }} />
        ))}
      {RINGS.map((ring, index) => (
        <g key={ring.rx} transform={`translate(0 34) rotate(${ring.rotate})`}>
          <g clipPath={`url(#${clip})`}>
            <ellipse className={styles.ring} rx={ring.rx} ry={ring.ry} />
            {SATELLITES.filter((s) => s.ring === index).map((s) => (
              <circle
                key={`${s.ring}-${s.begin}`}
                className={clsx(styles.satellite, s.accent && styles.satelliteAccent)}
                r={side === 'back' ? s.r * 0.72 : s.r}
                // The resting position, used when motion is off: spread around the front of the ring.
                cx={moving ? 0 : ring.rx * Math.cos(s.begin)}
                cy={moving ? 0 : Math.abs(ring.ry * Math.sin(s.begin)) * (side === 'back' ? -1 : 1)}
              >
                {moving && <animateMotion dur={`${s.dur}s`} begin={`${s.begin}s`} repeatCount="indefinite" path={ellipsePath(ring)} />}
              </circle>
            ))}
          </g>
        </g>
      ))}
    </svg>
  );
}

function Half({ side, gradientId, clipId }: { side: 'left' | 'right'; gradientId: string; clipId: string }): JSX.Element {
  const d = side === 'left' ? LEFT : RIGHT;
  const slices = Array.from({ length: DEPTH }, (_, i) => DEPTH - i); // back to front
  return (
    <div className={clsx(styles.half, side === 'left' ? styles.halfLeft : styles.halfRight)}>
      {slices.map((i) => (
        <svg key={i} className={styles.slice} viewBox={VIEW_BOX} style={{ transform: `translateZ(${-i * SLICE_PX}px)` }} focusable="false">
          <path d={d} fill={sideColour((i - 1) / (DEPTH - 1))} />
        </svg>
      ))}
      <svg className={styles.slice} viewBox={VIEW_BOX} focusable="false">
        <defs>
          <clipPath id={clipId}>
            <path d={d} />
          </clipPath>
        </defs>
        <path d={d} fill={`url(#${gradientId})`} />
        <g clipPath={`url(#${clipId})`}>
          <g transform="skewX(-22)">
            <rect className={styles.shine} x="-40" y="-10" width="26" height="110" />
          </g>
        </g>
        <path className={styles.edge} d={d} />
      </svg>
    </div>
  );
}

function HeroScene({ animated, className }: { animated: boolean; className?: string }): JSX.Element {
  const sceneRef = useRef<HTMLDivElement>(null);
  const [moving, setMoving] = useState(false);
  const gradientId = useSafeId('oak-face');
  const clipLeft = useSafeId('oak-clip-l');
  const clipRight = useSafeId('oak-clip-r');
  const orbitIds = { upper: useSafeId('oak-upper'), lower: useSafeId('oak-lower') };
  const orbitIdsFront = { upper: useSafeId('oak-upper-f'), lower: useSafeId('oak-lower-f') };

  useEffect(() => {
    if (!animated) return undefined;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (reduce.matches) return undefined;
    setMoving(true);

    // The mark leans toward the pointer anywhere over the hero section.
    const scene = sceneRef.current;
    const host = scene?.closest('section') ?? scene;
    if (!scene || !host) return undefined;
    let frame = 0;
    const onMove = (event: PointerEvent) => {
      const box = host.getBoundingClientRect();
      const x = (event.clientX - box.left) / box.width - 0.5;
      const y = (event.clientY - box.top) / box.height - 0.5;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        scene.style.setProperty('--oak-ry', `${(x * 26).toFixed(2)}deg`);
        scene.style.setProperty('--oak-rx', `${(-y * 16).toFixed(2)}deg`);
      });
    };
    const onLeave = () => {
      scene.style.setProperty('--oak-ry', '0deg');
      scene.style.setProperty('--oak-rx', '0deg');
    };
    host.addEventListener('pointermove', onMove);
    host.addEventListener('pointerleave', onLeave);
    return () => {
      cancelAnimationFrame(frame);
      host.removeEventListener('pointermove', onMove);
      host.removeEventListener('pointerleave', onLeave);
    };
  }, [animated]);

  return (
    <div ref={sceneRef} className={clsx(styles.scene, animated && styles.sceneAnimated, className)} aria-hidden="true">
      <svg width="0" height="0" className={styles.defs} focusable="false">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#FF7A52" />
            <stop offset="45%" stopColor="var(--ak-primary)" />
            <stop offset="100%" stopColor="var(--ak-primary-soft)" />
          </linearGradient>
        </defs>
      </svg>
      <div className={styles.sceneGlow} />
      <OrbitLayer side="back" ids={orbitIds} moving={moving} />
      <div className={styles.stage}>
        <div className={styles.pointerTilt}>
          <div className={styles.sway}>
            <Half side="left" gradientId={gradientId} clipId={clipLeft} />
            <Half side="right" gradientId={gradientId} clipId={clipRight} />
          </div>
        </div>
      </div>
      <div className={styles.shadow} />
      <OrbitLayer side="front" ids={orbitIdsFront} moving={moving} />
    </div>
  );
}

/**
 * The brand mark, drawn in code. The hero variant is a 3D scene: the mark's two halves fold
 * together, the extruded body tilts toward the pointer, and agents orbit it. It replaces the
 * hero video. The other variants are the flat mark, used in diagram hubs and calls to action.
 */
export default function OakMark({ variant = 'hero', animated = true, className }: OakMarkProps): JSX.Element {
  if (variant === 'hero') {
    return <HeroScene animated={animated} className={className} />;
  }
  return <FlatMark variant={variant} animated={animated} className={className} />;
}
