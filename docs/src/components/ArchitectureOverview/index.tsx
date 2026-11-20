import React, { type CSSProperties } from 'react';
import Link from '@docusaurus/Link';
import clsx from 'clsx';
import SectionHeader from '@site/src/components/ui/SectionHeader';
import styles from './styles.module.css';
import {
  CORE_LABEL,
  CORE_PILLS,
  DESTINATIONS,
  DESTINATIONS_LABEL,
  FLOW_WORDS,
  SOURCES,
  SOURCES_LABEL,
  type ArchCard,
  type Chip,
} from './data';

/* ─── Architecture ────────────────────────────────────────────────────────
   Three columns: what sends requests, the runtime, and what the runtime
   drives. The runtime panel is as tall as the columns beside it, so every
   card joins it with one straight rail across the gap: no bends, nothing
   to cross. The rails and their dots are drawn in the stylesheet, so the
   diagram needs no measuring and is complete without script. */

function ChipLink({ chip }: { chip: Chip }): JSX.Element {
  return (
    <Link to={chip.href} className={styles.chip} title={chip.name} aria-label={chip.name}>
      {chip.icon ?? <img src={chip.logo} alt="" loading="lazy" className={clsx(styles.chipImg, chip.mono && styles.mono)} />}
    </Link>
  );
}

/** A card and the rail that joins it to the runtime. `order` staggers the dots. */
function Card({ card, side, order }: { card: ArchCard; side: 'in' | 'out'; order: number }): JSX.Element {
  return (
    <div className={styles.card}>
      <h3 className={styles.cardTitle}>{card.title}</h3>
      {/* The chips are logos, named on hover. A touch screen has no hover, so there the names are
          written out once, in chip order. Each chip already carries its name for a screen reader. */}
      <p className={styles.names} aria-hidden="true">
        {card.chips.map((chip) => chip.name).join(', ')}
      </p>
      <div className={styles.chipRow}>
        {card.chips.map((chip) => (
          <ChipLink key={chip.name} chip={chip} />
        ))}
      </div>
      <span className={clsx(styles.rail, side === 'in' ? styles.railIn : styles.railOut)} aria-hidden="true">
        <span className={styles.dot} style={{ animationDelay: `${-order * 0.8 - (side === 'out' ? 1.2 : 0)}s` } as CSSProperties} />
      </span>
    </div>
  );
}

export default function ArchitectureOverview(): JSX.Element {
  return (
    <section id="architecture" className="ak-section">
      <div className="ak-container">
        <SectionHeader
          index="02"
          label="Architecture"
          title="One runtime between your channels and your agents"
          lead="Requests arrive from any channel or protocol. OAK runs your framework-native agents with sessions, guardrails, queues and sandboxes, on whichever cloud you choose."
        />

        <div className={styles.diagram}>
          <div className={styles.columns}>
            <div className={styles.column}>
              <p className={clsx('ak-label', styles.columnLabel)}>{SOURCES_LABEL}</p>
              <div className={styles.cards}>
                {SOURCES.map((card, index) => (
                  <Card key={card.title} card={card} side="in" order={index} />
                ))}
              </div>
            </div>

            <div className={styles.stackArrow} aria-hidden="true">
              &darr;
            </div>

            <div className={styles.column}>
              <p className={clsx('ak-label', styles.columnLabel, styles.labelCentre)}>{CORE_LABEL}</p>
              <div className={clsx('ak-dark', styles.core)}>
                <img src="/img/branding/oak-mark-orange.svg" alt="" className={styles.coreLogo} />
                <p className={clsx('ak-h3', styles.coreName)}>OAK runtime</p>
                <ul className={styles.capabilities}>
                  {CORE_PILLS.map((pill) => (
                    <li key={pill.label}>
                      <Link to={pill.href} className={styles.capability}>
                        {pill.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className={styles.stackArrow} aria-hidden="true">
              &darr;
            </div>

            <div className={styles.column}>
              <p className={clsx('ak-label', styles.columnLabel, styles.labelEnd)}>{DESTINATIONS_LABEL}</p>
              <div className={styles.cards}>
                {DESTINATIONS.map((card, index) => (
                  <Card key={card.title} card={card} side="out" order={index} />
                ))}
              </div>
            </div>
          </div>

          <p className={clsx('ak-label', styles.flow)}>
            <span>Request in</span>
            <span className={styles.flowWords}>
              {FLOW_WORDS.map((entry, index) => (
                <React.Fragment key={entry.word}>
                  {index > 0 && (
                    <span className={styles.flowSeparator} aria-hidden="true">
                      &rarr;
                    </span>
                  )}
                  <span className={styles.flowWord}>{entry.word}</span>
                </React.Fragment>
              ))}
            </span>
            <span>Response out</span>
          </p>
        </div>
      </div>
    </section>
  );
}
