import React, { useId } from 'react';
import clsx from 'clsx';
import styles from './styles.module.css';

/**
 * Small illustrations drawn in the Open Agent Kernel palette. They replace raster images
 * that carried the old colour scheme, and they follow the theme tokens, so they work in
 * both the dark and the light colour mode.
 */

const MARK_LEFT =
  'M19.74,39.48v15.79l12.48,5.06c4.39,1.76,7.26,6.01,7.26,10.73v15.79l-27.78-11.11c-7.07-2.83-11.7-9.67-11.7-17.27V0l27.79,11.11c7.06,2.83,11.69,9.67,11.69,17.27v19.07L19.74,39.48Z';
const MARK_RIGHT =
  'M86.86,0v58.47c0,7.6-4.64,14.44-11.7,17.27l-27.78,11.11v-23.69c0-4.72,2.87-8.97,7.26-10.73l12.48-5.06v-15.79l-19.74,7.97v-11.17c0-7.6,4.63-14.44,11.69-17.27L86.86,0Z';

function useGradientId(prefix: string): string {
  return `${prefix}-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
}

function OrangeGradient({ id }: { id: string }): JSX.Element {
  return (
    <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stopColor="var(--ak-primary)" />
      <stop offset="100%" stopColor="var(--ak-primary-soft)" />
    </linearGradient>
  );
}

export type PersonaKind = 'business' | 'developer' | 'engineer';

type PersonaArtProps = {
  kind: PersonaKind;
  className?: string;
};

/** Business outcomes: a rising chart with the last bar and the trend line in the accent. */
function BusinessArt({ grad }: { grad: string }): JSX.Element {
  const bars = [
    { x: 104, h: 30 },
    { x: 140, h: 46 },
    { x: 176, h: 64 },
  ];
  return (
    <>
      <line className={styles.faint} x1="84" y1="146" x2="262" y2="146" />
      <line className={styles.faint} x1="84" y1="112" x2="262" y2="112" strokeDasharray="3 6" />
      <line className={styles.faint} x1="84" y1="78" x2="262" y2="78" strokeDasharray="3 6" />
      {bars.map((b) => (
        <rect key={b.x} className={styles.soft} x={b.x} y={146 - b.h} width="24" height={b.h} rx="4" />
      ))}
      <rect x="212" y="56" width="24" height="90" rx="4" fill={`url(#${grad})`} />
      <polyline className={styles.accentLine} points="92,128 116,108 152,92 188,72 224,44" />
      <polyline className={styles.accentLine} points="208,42 226,42 226,60" />
      {[
        [116, 108],
        [152, 92],
        [188, 72],
      ].map(([cx, cy]) => (
        <circle key={cx} className={styles.node} cx={cx} cy={cy} r="4" />
      ))}
    </>
  );
}

/** Building software: an editor window with one highlighted line and a caret. */
function DeveloperArt({ grad }: { grad: string }): JSX.Element {
  const lines = [
    { x: 118, y: 80, w: 58 },
    { x: 132, y: 96, w: 86 },
    { x: 132, y: 128, w: 46 },
    { x: 118, y: 144, w: 30 },
  ];
  return (
    <>
      <rect className={styles.panel} x="92" y="36" width="160" height="124" rx="12" />
      <line className={styles.line} x1="92" y1="60" x2="252" y2="60" />
      <circle className={styles.dotAccent} cx="108" cy="48" r="3.5" />
      <circle className={styles.dot} cx="121" cy="48" r="3.5" />
      <circle className={styles.dot} cx="134" cy="48" r="3.5" />
      {lines.map((l) => (
        <rect key={l.y} className={styles.code} x={l.x} y={l.y} width={l.w} height="6" rx="3" />
      ))}
      <rect x="132" y="112" width="70" height="6" rx="3" fill={`url(#${grad})`} />
      <rect className={styles.caret} x="208" y="108" width="3" height="14" rx="1.5" />
      <polyline className={styles.accentLine} points="80,82 64,98 80,114" />
      <polyline className={styles.accentLine} points="264,82 280,98 264,114" />
    </>
  );
}

/** Agent engineering: frameworks and tools as nodes around the kernel. */
function EngineerArt({ grad }: { grad: string }): JSX.Element {
  const cx = 172;
  const cy = 96;
  const nodes = [
    [94, 52],
    [250, 52],
    [70, 110],
    [274, 110],
    [112, 160],
    [232, 160],
  ];
  return (
    <>
      <ellipse className={styles.faint} cx={cx} cy={cy} rx="118" ry="70" strokeDasharray="2 7" />
      {nodes.map(([x, y]) => (
        <line key={`${x}-${y}`} className={styles.line} x1={cx} y1={cy} x2={x} y2={y} />
      ))}
      {nodes.map(([x, y], i) => (
        <circle key={`${x}-${y}`} className={i === 1 ? styles.nodeAccent : styles.node} cx={x} cy={y} r={i % 2 ? 7 : 9} />
      ))}
      <rect className={styles.panel} x={cx - 30} y={cy - 30} width="60" height="60" rx="14" />
      <g transform={`translate(${cx - 17} ${cy - 17}) scale(0.392)`} fill={`url(#${grad})`}>
        <path d={MARK_LEFT} />
        <path d={MARK_RIGHT} />
      </g>
    </>
  );
}

export function PersonaArt({ kind, className }: PersonaArtProps): JSX.Element {
  const grad = useGradientId('persona-art');
  return (
    <svg className={clsx(styles.art, className)} viewBox="0 0 344 192" aria-hidden="true" focusable="false">
      <defs>
        <OrangeGradient id={grad} />
      </defs>
      {kind === 'business' && <BusinessArt grad={grad} />}
      {kind === 'developer' && <DeveloperArt grad={grad} />}
      {kind === 'engineer' && <EngineerArt grad={grad} />}
    </svg>
  );
}

type CertSealProps = {
  /** A round seal for a certification, a shield for an audit. */
  shape: 'seal' | 'shield';
  className?: string;
};

export function CertSeal({ shape, className }: CertSealProps): JSX.Element {
  const grad = useGradientId('cert-seal');
  return (
    <svg className={clsx(styles.art, className)} viewBox="0 0 72 72" aria-hidden="true" focusable="false">
      <defs>
        <OrangeGradient id={grad} />
      </defs>
      {shape === 'seal' ? (
        <>
          <circle className={styles.faint} cx="36" cy="36" r="31" strokeDasharray="2 5" />
          <circle className={styles.panel} cx="36" cy="36" r="24" />
        </>
      ) : (
        <path
          className={styles.panel}
          d="M36 6 60 15v19c0 14.6-9.6 26.4-24 32C21.6 60.4 12 48.6 12 34V15L36 6Z"
        />
      )}
      <polyline className={styles.check} stroke={`url(#${grad})`} points="25,37 33,45 48,28" />
    </svg>
  );
}
