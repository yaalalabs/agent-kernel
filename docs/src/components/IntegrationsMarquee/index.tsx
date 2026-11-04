import React from "react";
import Link from "@docusaurus/Link";
import clsx from "clsx";
import styles from "./styles.module.css";
import { INTEGRATION_ROWS, type IntegrationItem, type IntegrationRow } from "./data";

/** Default seconds of animation per tile; a row overrides it with `secondsPerTile` to scroll faster or slower. */
const DEFAULT_SECONDS_PER_TILE = 3.2;

/** Copies of each row rendered on the track; the keyframe slides by exactly one copy. Keep in sync with styles.module.css. */
const TRACK_COPIES = 3;

function TileLogo({ item }: { item: IntegrationItem }) {
  if (item.icon) {
    return (
      <span className={styles.logoWrap} aria-hidden="true">
        {item.icon}
      </span>
    );
  }
  return (
    <span className={clsx(styles.logoWrap, item.wide && styles.logoWrapWide)} aria-hidden="true">
      <img
        src={item.logo}
        alt=""
        loading="lazy"
        className={clsx(styles.logo, item.mono && styles.mono, item.wide && styles.logoWide)}
      />
    </span>
  );
}

function Tile({ item, decorative }: { item: IntegrationItem; decorative: boolean }) {
  return (
    <Link
      to={item.href}
      className={styles.tile}
      title={item.title ?? `${item.name}: ${item.role}`}
      tabIndex={decorative ? -1 : undefined}
      aria-hidden={decorative || undefined}
    >
      <TileLogo item={item} />
      <span className={styles.text}>
        <span className={styles.name}>
          {item.name}
          {item.soon && <span className={styles.soon}>soon</span>}
        </span>
        <span className={styles.role}>{item.role}</span>
      </span>
    </Link>
  );
}

function MarqueeRow({ row, reverse }: { row: IntegrationRow; reverse: boolean }) {
  const secondsPerTile = row.secondsPerTile ?? DEFAULT_SECONDS_PER_TILE;
  const duration = `${Math.round(row.items.length * secondsPerTile)}s`;
  const copies = Array.from({ length: TRACK_COPIES }, (_, copy) => copy);

  return (
    <div className={styles.row}>
      <div className={styles.rowLabel}>{row.title}</div>
      <div className={styles.viewport}>
        <div
          className={clsx(styles.track, reverse && styles.trackReverse)}
          style={{ "--marquee-duration": duration } as React.CSSProperties}
        >
          {copies.map((copy) => (
            <div key={copy} className={styles.group}>
              {row.items.map((item) => (
                <Tile key={item.name} item={item} decorative={copy > 0} />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function IntegrationsMarquee() {
  return (
    <section id="integrations" className={styles.section}>
      <div className={styles.topGlow} />

      <div className={styles.header}>
        <div className={styles.badge}>
          <span className={styles.badgeStar}>✦</span>
          Integrates Seamlessly
        </div>
        <h2 className={styles.title}>Popular integrations</h2>
        <p className={styles.subtitle}>
          Frameworks, channels, memory, clouds, and observability. Plug in what
          you already run.
        </p>
      </div>

      <div className={styles.rows}>
        {INTEGRATION_ROWS.map((row, index) => (
          <MarqueeRow key={row.title} row={row} reverse={index % 2 === 1} />
        ))}
      </div>
    </section>
  );
}
