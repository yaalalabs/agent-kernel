import React, { useRef, useState, type ReactNode } from 'react';
import useBrokenLinks from '@docusaurus/useBrokenLinks';
import Link from '@docusaurus/Link';
import CodeBlock from '@theme/CodeBlock';
import clsx from 'clsx';
import SectionHeader from '@site/src/components/ui/SectionHeader';
import Reveal from '@site/src/components/ui/Reveal';
import { StepTimeline, type Step } from '@site/src/components/StepTimeline';
import styles from '@site/src/pages/persona.module.css';

/**
 * The parts the three persona pages (business leader, developer, AI engineer) are built from,
 * so that the pages read as one set: a numbered section, a tab set, a framed code sample, a row
 * of documentation links and the links to the other levels.
 */

/* ─── Journey ─────────────────────────────────────────────────────────────
   The step rail and the sections it lists, in one box. The rail stays in view
   while the box is on screen and leaves with its last section. */

export function Journey({ steps, children }: { steps: readonly Step[]; children: ReactNode }): JSX.Element {
  return (
    <div className={styles.journey}>
      <StepTimeline steps={steps} />
      {children}
    </div>
  );
}

/* ─── Section ─────────────────────────────────────────────────────────────
   One step of a persona page. Its id is the target of the step rail. */

type PersonaSectionProps = {
  /** Anchor id, matched by a step in the page's `StepTimeline`. */
  id: string;
  /** Two-digit step number. */
  index: string;
  label: string;
  title: ReactNode;
  lead?: ReactNode;
  children: ReactNode;
};

export function PersonaSection({ id, index, label, title, lead, children }: PersonaSectionProps): JSX.Element {
  // Tell the build that this id exists, so links to it are checked.
  useBrokenLinks().collectAnchor(id);
  return (
    <section id={id} className={styles.section} aria-labelledby={`${id}-title`}>
      <Reveal className="ak-container">
        <SectionHeader index={index} label={label} title={title} lead={lead} id={`${id}-title`} />
        {children}
      </Reveal>
    </section>
  );
}

/* ─── Tabs ────────────────────────────────────────────────────────────────
   A tab set that follows the ARIA tabs pattern: the arrow keys, Home and End
   move between tabs, and Tab moves on to the panel. */

export type TabItem = {
  id: string;
  label: string;
  content: ReactNode;
};

type TabsProps = {
  /** Unique on the page: it prefixes the ids that tie tabs to the panel. */
  name: string;
  /** Accessible name of the tab list. */
  label: string;
  items: readonly TabItem[];
};

export function Tabs({ name, label, items }: TabsProps): JSX.Element {
  const [active, setActive] = useState(0);
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  const current = items[active];

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const last = items.length - 1;
    const moves: Record<string, number> = {
      ArrowRight: active === last ? 0 : active + 1,
      ArrowLeft: active === 0 ? last : active - 1,
      Home: 0,
      End: last,
    };
    const next = moves[event.key];
    if (next === undefined) return;
    event.preventDefault();
    setActive(next);
    tabs.current[next]?.focus();
  };

  return (
    <div className={styles.tabs}>
      <div className={styles.tabList} role="tablist" aria-label={label} onKeyDown={onKeyDown}>
        {items.map((item, index) => (
          <button
            key={item.id}
            ref={(node) => {
              tabs.current[index] = node;
            }}
            id={`${name}-tab-${item.id}`}
            type="button"
            role="tab"
            aria-selected={index === active}
            aria-controls={`${name}-panel`}
            tabIndex={index === active ? 0 : -1}
            className={clsx(styles.tab, index === active && styles.tabActive)}
            onClick={() => setActive(index)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div
        id={`${name}-panel`}
        role="tabpanel"
        aria-labelledby={`${name}-tab-${current.id}`}
        tabIndex={0}
        className={styles.tabPanel}
      >
        {current.content}
      </div>
    </div>
  );
}

/* ─── Code sample ─────────────────────────────────────────────────────────
   A code block in the site's flat frame, with its file name or a caption. */

type CodeSampleProps = {
  title: string;
  language: string;
  children: string;
  className?: string;
};

export function CodeSample({ title, language, children, className }: CodeSampleProps): JSX.Element {
  return (
    <div className={clsx(styles.code, className)}>
      <CodeBlock language={language} title={title}>
        {children}
      </CodeBlock>
    </div>
  );
}

/* ─── Documentation links ─────────────────────────────────────────────────── */

export type DocLink = { label: string; to: string };

export function DocLinks({ links }: { links: readonly DocLink[] }): JSX.Element {
  return (
    <ul className={styles.docLinks}>
      {links.map((link) => (
        <li key={link.to}>
          <Link to={link.to} className="ak-link">
            {link.label}
          </Link>
        </li>
      ))}
    </ul>
  );
}

/* ─── Other levels ────────────────────────────────────────────────────────
   The end of every persona page: the other two levels, then the two pages
   that go wider. It replaces the "back to path selection" button. */

export type LevelId = 'business-leader' | 'developer' | 'ai-engineer';

const LEVELS: ReadonlyArray<{ id: LevelId; tag: string; title: string; line: string }> = [
  {
    id: 'business-leader',
    tag: 'Level 01',
    title: 'For business leaders',
    line: 'Where agents pay off, what OAK is in plain words, and what adopting it commits you to.',
  },
  {
    id: 'developer',
    tag: 'Level 02',
    title: 'For developers',
    line: 'From an empty folder to an agent that is deployed and tested.',
  },
  {
    id: 'ai-engineer',
    tag: 'Level 03',
    title: 'For AI engineers',
    line: 'How the runtime compares, where it sits in a request, and what you can build on.',
  },
];

const WIDER = [
  { to: '/features', tag: 'Reference', title: 'Features', line: 'Every capability of the runtime, by area.' },
  { to: '/use-cases', tag: 'Reference', title: 'Use cases', line: 'What teams build with OAK, by industry.' },
];

export function OtherLevels({ current }: { current: LevelId }): JSX.Element {
  const rows = [
    ...LEVELS.filter((level) => level.id !== current).map((level) => ({ ...level, to: `/${level.id}` })),
    ...WIDER,
  ];
  return (
    <nav className={styles.next} aria-labelledby="keep-reading">
      <div className="ak-container">
        <h2 id="keep-reading" className="ak-label">
          Keep reading
        </h2>
        <ul className={styles.nextList}>
          {rows.map((row) => (
            <li key={row.to}>
              <Link to={row.to} className={styles.nextRow}>
                <span className={clsx('ak-label', styles.nextTag)}>{row.tag}</span>
                <span className={clsx('ak-h4', styles.nextTitle)}>{row.title}</span>
                <span className={clsx('ak-body', styles.nextLine)}>{row.line}</span>
                <span className={styles.nextArrow} aria-hidden="true">
                  &rarr;
                </span>
              </Link>
            </li>
          ))}
        </ul>
        <Link to="/#levels" className="ak-link">
          All three levels
        </Link>
      </div>
    </nav>
  );
}
