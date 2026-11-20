import React from 'react';
import clsx from 'clsx';
import styles from './styles.module.css';

/**
 * Small marks drawn in the Open Agent Kernel palette. Every colour is a theme token, so they
 * work in both the dark and the light colour mode.
 */

type CertSealProps = {
  /** A round seal for a certification, a shield for an audit. */
  shape: 'seal' | 'shield';
  className?: string;
};

export function CertSeal({ shape, className }: CertSealProps): JSX.Element {
  return (
    <svg className={clsx(styles.art, className)} viewBox="0 0 72 72" aria-hidden="true" focusable="false">
      {shape === 'seal' ? (
        <>
          <circle className={styles.faint} cx="36" cy="36" r="31" strokeDasharray="2 5" />
          <circle className={styles.panel} cx="36" cy="36" r="24" />
        </>
      ) : (
        <path className={styles.panel} d="M36 6 60 15v19c0 14.6-9.6 26.4-24 32C21.6 60.4 12 48.6 12 34V15L36 6Z" />
      )}
      <polyline className={styles.check} points="25,37 33,45 48,28" />
    </svg>
  );
}
