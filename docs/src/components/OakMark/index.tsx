import React, { useId } from 'react';
import clsx from 'clsx';
import styles from './styles.module.css';

type OakMarkProps = {
  /** Sizing and glow strength: the home hero, a diagram hub, or a call-to-action. */
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

/**
 * The brand mark, drawn in code: an orange gradient fill over a soft glow, with a
 * light outline that draws in once. Replaces the hero video and the CTA image.
 */
export default function OakMark({ variant = 'hero', animated = true, className }: OakMarkProps): JSX.Element {
  const gradientId = `oak-mark-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
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
