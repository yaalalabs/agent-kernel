import React, { useCallback, useEffect, useRef, useState } from 'react';
import Link from '@docusaurus/Link';
import clsx from 'clsx';
import SectionHeader from '@site/src/components/ui/SectionHeader';
import Floor from '@site/src/components/DotField/Floor';
import { INTEGRATION_ROWS, type IntegrationItem } from './integrations.data';
import styles from './integrations.module.css';

/* ─── Works with: every integration, one stage at a time ──────────────────
   The integrations are grouped by the six stages of section 01. On a large
   screen the section stays in view while the page scrolls, and each scroll
   step brings the next stage and its integrations forward. The list of
   stages on the left shows where the reader is and is also a control.

   Everything is in the page from the first render: without script, on small
   screens, on short windows and with reduced motion, the six groups are
   simply stacked. The data file is the one the marquee uses, so there is one
   list to maintain, and an integration whose role is not mapped below still
   appears, under "More" in the last group. */

type IntegrationSet = { title: string; roles: string[] };
type Group = {
  id: string;
  name: string;
  title: string;
  sets: IntegrationSet[];
};

const GROUPS: Group[] = [
  {
    id: 'build',
    name: 'Build',
    title: 'Build with the framework you already know',
    sets: [
      { title: 'Agent frameworks', roles: ['Framework'] },
      { title: 'Model gateway', roles: ['LLM gateway'] },
      { title: 'Coding assistants', roles: ['Agent skills'] },
    ],
  },
  {
    id: 'connect',
    name: 'Connect',
    title: 'Connect to the channels your users are on',
    sets: [
      { title: 'Channels', roles: ['Channel', 'Voice integration'] },
      { title: 'Protocols and APIs', roles: ['Protocol', 'API'] },
    ],
  },
  {
    id: 'remember',
    name: 'Remember',
    title: 'Remember in the stores you already run',
    sets: [
      { title: 'Session and state stores', roles: ['Memory'] },
      {
        title: 'Knowledge',
        roles: ['Knowledge store', 'Vector knowledge', 'Graph knowledge', 'SQL knowledge'],
      },
    ],
  },
  {
    id: 'guard',
    name: 'Guard',
    title: 'Guard with your identity provider and your policies',
    sets: [
      { title: 'Identity', roles: ['Identity'] },
      { title: 'Secrets', roles: ['Secrets'] },
      { title: 'Guardrails', roles: ['Guardrail'] },
      { title: 'Sandboxes', roles: ['Sandbox'] },
    ],
  },
  {
    id: 'scale',
    name: 'Scale',
    title: 'Scale on the cloud you already use',
    sets: [
      {
        title: 'Clouds',
        roles: ['Serverless', 'Containers', 'Serverless & containers', 'On-prem', 'Gateway'],
      },
      {
        title: 'Infrastructure',
        roles: ['Infrastructure as code', 'Chart', 'Autoscaling', 'Scheduler'],
      },
      { title: 'Queues', roles: ['Queue'] },
    ],
  },
  {
    id: 'observe',
    name: 'Observe',
    title: 'Observe and test with the tools you trust',
    sets: [
      { title: 'Tracing', roles: ['Tracing'] },
      { title: 'Evaluation', roles: ['Evaluator'] },
    ],
  },
];

const ALL_ITEMS: IntegrationItem[] = INTEGRATION_ROWS.flatMap((row) => row.items);
const MAPPED_ROLES = new Set(GROUPS.flatMap((group) => group.sets.flatMap((set) => set.roles)));
const UNMAPPED = ALL_ITEMS.filter((item) => !MAPPED_ROLES.has(item.role));

type Panel = {
  id: string;
  name: string;
  title: string;
  count: number;
  sets: Array<{ title: string; items: IntegrationItem[] }>;
};

const PANELS: Panel[] = GROUPS.map((group, index) => {
  const sets = group.sets
    .map((set) => ({
      title: set.title,
      items: ALL_ITEMS.filter((item) => set.roles.includes(item.role)),
    }))
    .concat(index === GROUPS.length - 1 ? [{ title: 'More', items: UNMAPPED }] : [])
    .filter((set) => set.items.length > 0);
  return {
    id: group.id,
    name: group.name,
    title: group.title,
    sets,
    count: sets.reduce((sum, set) => sum + set.items.length, 0),
  };
});

// The section pins only where the pinned frame is sure to fit.
const PIN_QUERY = '(min-width: 997px) and (min-height: 700px) and (prefers-reduced-motion: no-preference)';

function Logo({ item }: { item: IntegrationItem }): JSX.Element {
  return (
    <span className={styles.logo} aria-hidden="true">
      {item.icon ?? <img src={item.logo} alt="" loading="lazy" className={clsx(item.mono && styles.mono)} />}
    </span>
  );
}

export function Integrations(): JSX.Element {
  const section = useRef<HTMLElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(false);
  const [active, setActive] = useState(0);

  useEffect(() => {
    const query = window.matchMedia(PIN_QUERY);
    const update = () => setPinned(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  // While pinned, the scroll position inside the section picks the stage.
  useEffect(() => {
    const node = section.current;
    const sticky = frame.current;
    if (!pinned || !node || !sticky) return undefined;
    let waiting = 0;
    const read = () => {
      waiting = 0;
      const bounds = node.getBoundingClientRect();
      const travel = bounds.height - sticky.offsetHeight;
      const top = parseFloat(getComputedStyle(sticky).top) || 0;
      const progress = travel > 0 ? Math.max(0, Math.min((top - bounds.top) / travel, 1)) : 0;
      node.style.setProperty('--progress', progress.toFixed(4));
      setActive(Math.min(PANELS.length - 1, Math.floor(progress * PANELS.length)));
    };
    const onScroll = () => {
      if (!waiting) waiting = requestAnimationFrame(read);
    };
    read();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      cancelAnimationFrame(waiting);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, [pinned]);

  // A stage in the list scrolls the page to the middle of that stage's step.
  const goTo = useCallback((index: number) => {
    const node = section.current;
    const sticky = frame.current;
    if (!node || !sticky) return;
    const travel = node.offsetHeight - sticky.offsetHeight;
    const top = parseFloat(getComputedStyle(sticky).top) || 0;
    const start = node.getBoundingClientRect().top + window.scrollY - top;
    window.scrollTo({
      top: start + ((index + 0.5) / PANELS.length) * travel,
      behavior: 'smooth',
    });
  }, []);

  return (
    <section
      ref={section}
      id="integrations"
      className={clsx(styles.section, pinned && styles.pinned)}
      style={{ '--steps': PANELS.length } as React.CSSProperties}
    >
      <div ref={frame} className={styles.frame}>
        {/* A floor of dots along the bottom edge; a ripple crosses it when the stage changes */}
        {pinned && <Floor stage={active} className={styles.floor} />}
        <div className={clsx('ak-container', styles.layout)}>
          <div className={styles.aside}>
            <SectionHeader
              index="03"
              label="Works with"
              title="Plug in what you already run"
              lead={`${ALL_ITEMS.length} integrations, and every one is an adapter. Swap one without touching the others.`}
            />

            {/* The stage list: shown only while the section is pinned */}
            <div className={styles.steps} role={pinned ? 'tablist' : undefined} aria-label="Integration groups" aria-orientation="vertical">
              <span className={styles.marker} aria-hidden="true" />
              {PANELS.map((panel, index) => (
                <button
                  key={panel.id}
                  type="button"
                  id={`integrations-tab-${panel.id}`}
                  role={pinned ? 'tab' : undefined}
                  aria-selected={pinned ? index === active : undefined}
                  aria-controls={`integrations-panel-${panel.id}`}
                  className={clsx(styles.step, index === active && styles.stepActive)}
                  onClick={() => goTo(index)}
                >
                  <span className={styles.stepIndex}>{String(index + 1).padStart(2, '0')}</span>
                  <span className={styles.stepName}>{panel.name}</span>
                  <span className={styles.stepCount}>{panel.count}</span>
                </button>
              ))}
            </div>

            <Link to="/docs/integrations/overview" className={clsx('ak-link', styles.all)}>
              Read the integration guides
            </Link>
          </div>

          <div className={styles.panels}>
            {PANELS.map((panel, index) => {
              // Chips come in one after another across the whole panel, not set by set.
              let order = 0;
              return (
                <div
                  key={panel.id}
                  id={`integrations-panel-${panel.id}`}
                  role={pinned ? 'tabpanel' : undefined}
                  aria-labelledby={pinned ? `integrations-tab-${panel.id}` : undefined}
                  className={clsx(styles.panel, index === active && styles.panelActive)}
                >
                  <p className={clsx('ak-label', styles.panelLabel)}>
                    <span className="ak-label__index">{String(index + 1).padStart(2, '0')}</span>
                    {panel.name}
                  </p>
                  <h3 className="ak-h3">{panel.title}</h3>
                  <div className={styles.sets}>
                    {panel.sets.map((set) => (
                      <div key={set.title} className={styles.set}>
                        <p className={clsx('ak-label', styles.setTitle)}>
                          {set.title}
                          <span className={styles.setCount}>{set.items.length}</span>
                        </p>
                        <ul className={styles.chips}>
                          {set.items.map((item) => (
                            <li key={`${item.name}-${item.role}`} style={{ '--i': order++ } as React.CSSProperties}>
                              <Link to={item.href} className={styles.chip} title={item.title}>
                                <Logo item={item} />
                                <span>{item.name}</span>
                              </Link>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
