import React from 'react';
import Link from '@docusaurus/Link';
import clsx from 'clsx';
import styles from './announcement.module.css';

/* ─── Announcement ────────────────────────────────────────────────────────
   One line above the hero for the newest capability. Replace the text and the
   link when something newer ships; older items live in the docs changelog. */

export function Announcement(): JSX.Element {
  return (
    <aside className={styles.bar} aria-label="What is new">
      <div className={clsx('ak-container', styles.inner)}>
        <span className={clsx('ak-tag', styles.tag)}>New</span>
        <p className={styles.text}>
          <strong>Identity provider support.</strong> Auth0, Keycloak, Okta, Cognito, Entra ID or Firebase now
          authenticates every surface.
        </p>
        <Link to="/docs/advanced/identity-and-access" className={clsx('ak-link', styles.link)}>
          Read more
        </Link>
      </div>
    </aside>
  );
}
