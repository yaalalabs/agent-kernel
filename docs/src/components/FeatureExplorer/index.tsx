import React, { useCallback, useRef, useState } from "react";
import Link from "@docusaurus/Link";
import clsx from "clsx";
import styles from "./styles.module.css";
import { EXAMPLES_BASE, FEATURE_TABS, type FeatureCard } from "./data";

function Card({ card }: { card: FeatureCard }) {
  return (
    <article className={styles.card}>
      <h3 className={styles.cardTitle}>{card.title}</h3>
      <p className={styles.cardBody}>{card.description}</p>
      <div className={styles.tagRow}>
        {card.tags.map((tag) => (
          <span key={tag} className={styles.tag}>
            {tag}
          </span>
        ))}
      </div>
      <div className={styles.linkRow}>
        <Link to={card.docs} className={styles.cardLink}>
          Docs <span aria-hidden="true">→</span>
        </Link>
        {card.example && (
          <Link to={`${EXAMPLES_BASE}/${card.example}`} className={styles.cardLink}>
            Example <span aria-hidden="true">→</span>
          </Link>
        )}
      </div>
    </article>
  );
}

export default function FeatureExplorer() {
  const [activeIndex, setActiveIndex] = useState(0);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const active = FEATURE_TABS[activeIndex];

  // Left/Right/Home/End move between tabs, matching the WAI-ARIA tabs pattern.
  const onTabKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
      const count = FEATURE_TABS.length;
      let next: number | null = null;
      if (event.key === "ArrowRight") next = (index + 1) % count;
      else if (event.key === "ArrowLeft") next = (index - 1 + count) % count;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = count - 1;
      if (next === null) return;
      event.preventDefault();
      setActiveIndex(next);
      tabRefs.current[next]?.focus();
    },
    [],
  );

  return (
    <section id="features" className={styles.section}>
      <div className={styles.topGlow} />

      <div className={styles.header}>
        <div className={styles.badge}>
          <span className={styles.badgeStar}>✦</span>
          Features
        </div>
        <h2 className={styles.title}>Everything you need for production agents. In one runtime.</h2>
        <p className={styles.subtitle}>
          One runtime for frameworks, channels, memory, guardrails, sandboxes and deployment, with the
          observability and testing an enterprise team actually trusts.
        </p>
      </div>

      <div className={styles.explorer}>
        <div className={styles.tabs} role="tablist" aria-label="Agent Kernel features">
          {FEATURE_TABS.map((tab, index) => {
            const selected = index === activeIndex;
            return (
              <button
                key={tab.key}
                ref={(el) => {
                  tabRefs.current[index] = el;
                }}
                type="button"
                role="tab"
                id={`feature-tab-${tab.key}`}
                aria-selected={selected}
                aria-controls={`feature-panel-${tab.key}`}
                tabIndex={selected ? 0 : -1}
                className={clsx(styles.tab, selected && styles.tabActive)}
                onClick={() => setActiveIndex(index)}
                onKeyDown={(event) => onTabKeyDown(event, index)}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        <div
          key={active.key}
          role="tabpanel"
          id={`feature-panel-${active.key}`}
          aria-labelledby={`feature-tab-${active.key}`}
          className={styles.panel}
        >
          <div className={styles.intro}>
            <h3 className={styles.introTitle}>{active.label}</h3>
            <p className={styles.introBody}>{active.description}</p>
          </div>
          <div className={styles.grid}>
            {active.cards.map((card) => (
              <Card key={card.title} card={card} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
