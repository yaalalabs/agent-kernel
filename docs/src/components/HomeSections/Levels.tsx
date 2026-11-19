import React, { useEffect, useRef, useState } from 'react';
import Link from '@docusaurus/Link';
import useBrokenLinks from '@docusaurus/useBrokenLinks';
import clsx from 'clsx';
import SectionHeader from '@site/src/components/ui/SectionHeader';
import LevelStack from '@site/src/components/LevelStack';
import styles from './levels.module.css';

/* ─── Choose your path: three levels of one stack ─────────────────────────
   The three guided tours are the three layers of one drawing: the outcome on
   top, the code in the middle, the runtime underneath. The drawing and the
   list are one control: a row lights its layer, and a layer lights its row.
   Until the visitor points at something, the light walks down the stack. */

type Level = { to: string; tag: string; title: string; layer: string; text: string };

const LEVELS: Level[] = [
  {
    to: '/business-leader',
    tag: 'No code required',
    title: 'Business leader',
    layer: 'The outcome',
    text: 'You want agents that work inside real business workflows, without owning the technical detail.',
  },
  {
    to: '/developer',
    tag: 'Some coding',
    title: 'Developer',
    layer: 'The code',
    text: 'You build software and want to ship a first robust agent without learning a new stack.',
  },
  {
    to: '/ai-engineer',
    tag: 'Deep tech',
    title: 'AI engineer',
    layer: 'The runtime',
    text: 'You already work with LLMs and agent frameworks, and need a production runtime that stays out of your way.',
  },
];

const STEP_MS = 2800;

export function Levels(): JSX.Element {
  // The persona pages link back to this section: tell the build that the id exists.
  useBrokenLinks().collectAnchor('levels');
  const section = useRef<HTMLElement>(null);
  const [active, setActive] = useState(0);
  // Once the visitor has pointed at a level, the light stops walking on its own.
  const [held, setHeld] = useState(false);

  useEffect(() => {
    const node = section.current;
    if (held || !node) return undefined;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined;
    let timer = 0;
    const seen = new IntersectionObserver(
      ([entry]) => {
        window.clearInterval(timer);
        if (entry.isIntersecting) {
          timer = window.setInterval(() => setActive((level) => (level + 1) % LEVELS.length), STEP_MS);
        }
      },
      { threshold: 0.3 },
    );
    seen.observe(node);
    return () => {
      window.clearInterval(timer);
      seen.disconnect();
    };
  }, [held]);

  const choose = (level: number) => {
    setHeld(true);
    setActive(level);
  };

  return (
    <section ref={section} id="levels" className="ak-section">
      <div className="ak-container">
        <SectionHeader
          index="05"
          label="Choose your path"
          title="OAK, explained for your level of expertise"
          lead="Three guided tours of the same stack. Pick how deep you want to go."
        />

        <div className={styles.layout}>
          <div className={styles.art}>
            <LevelStack active={active} onActivate={choose} />
          </div>

          <ol className={styles.rows}>
            {LEVELS.map((level, index) => (
              <li key={level.to}>
                <Link
                  to={level.to}
                  className={clsx(styles.row, index === active && styles.rowActive)}
                  onPointerEnter={() => choose(index)}
                  onFocus={() => choose(index)}
                >
                  <span className={styles.rowIndex}>{`0${index + 1}`}</span>
                  <span className={styles.rowBody}>
                    <span className={clsx('ak-label', styles.rowTag)}>
                      {level.layer}
                      <span className={styles.rowTagSep} aria-hidden="true">
                        /
                      </span>
                      {level.tag}
                    </span>
                    <span className={clsx('ak-h2', styles.rowTitle)}>{level.title}</span>
                    <span className={clsx('ak-body', styles.rowText)}>{level.text}</span>
                  </span>
                  <span className={styles.rowGo} aria-hidden="true">
                    &rarr;
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
