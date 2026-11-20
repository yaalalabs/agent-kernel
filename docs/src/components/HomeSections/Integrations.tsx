import React, { useCallback, useEffect, useRef, useState } from 'react';
import useIsomorphicLayoutEffect from '@docusaurus/useIsomorphicLayoutEffect';
import Link from '@docusaurus/Link';
import clsx from 'clsx';
import { TbChevronDown } from 'react-icons/tb';
import SectionHeader from '@site/src/components/ui/SectionHeader';
import Floor from '@site/src/components/DotField/Floor';
import { INTEGRATION_ROWS, type IntegrationItem } from './integrations.data';
import styles from './integrations.module.css';

/* ─── Works with: every integration, one stage at a time ──────────────────
   The integrations are grouped by the six stages of section 01. On a large
   screen the section stays in view while the page scrolls, and each scroll
   step brings the next stage and its integrations forward. The list of
   stages on the left shows where the reader is and is also a control.

   Everything is in the page from the first render: without script, on short
   windows and with reduced motion, the six groups are simply stacked.

   On a small screen the six groups would run to more than five screens, so
   they fold: each group's heading opens and closes its integrations, and the
   first group starts open. The stylesheet folds them before script runs, and
   a noscript rule unfolds them where script never will.

   The data file is the one the marquee uses, so there is one list to
   maintain, and an integration whose role is not mapped below still appears,
   under "More" in the last group. */

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

// The section pins only where the pinned frame is likely to fit. Whether it does is then measured.
const PIN_QUERY = '(min-width: 997px) and (min-height: 700px) and (prefers-reduced-motion: no-preference)';
// Below this width the groups fold (the same breakpoint as the stylesheet).
const FOLD_QUERY = '(max-width: 996px)';

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
  const aside = useRef<HTMLDivElement>(null);
  const panels = useRef<HTMLDivElement>(null);
  const panelNodes = useRef<Array<HTMLDivElement | null>>([]);
  const setNodes = useRef<Array<HTMLDivElement | null>>([]);
  // The section pins where the window is roomy enough (PIN_QUERY) and the tallest group fits
  // the pinned frame. The second is measured, because it depends on how the chips wrap.
  const [roomy, setRoomy] = useState(false);
  const [fits, setFits] = useState(true);
  const pinned = roomy && fits;
  const [active, setActive] = useState(0);
  const [folded, setFolded] = useState(false);
  // Which groups are open while folded. The first one, to begin with.
  const [open, setOpen] = useState<boolean[]>(() => PANELS.map((_, index) => index === 0));

  useEffect(() => {
    const pin = window.matchMedia(PIN_QUERY);
    const fold = window.matchMedia(FOLD_QUERY);
    const update = () => {
      setRoomy(pin.matches);
      setFits(true);
      setFolded(fold.matches);
    };
    update();
    pin.addEventListener('change', update);
    fold.addEventListener('change', update);
    return () => {
      pin.removeEventListener('change', update);
      fold.removeEventListener('change', update);
    };
  }, []);

  const toggle = (index: number) => setOpen((current) => current.map((value, at) => (at === index ? !value : value)));

  // While folded, a closed group is hidden "until found", like the pinned panels below:
  // find-in-page still searches it, and a match opens it.
  useIsomorphicLayoutEffect(() => {
    const searchable = 'onbeforematch' in document.documentElement;
    setNodes.current.forEach((sets, index) => {
      if (!sets) return;
      if (!folded || open[index]) sets.removeAttribute('hidden');
      else sets.setAttribute('hidden', searchable ? 'until-found' : '');
    });
  }, [folded, open]);

  useEffect(() => {
    if (!folded) return undefined;
    const nodes = setNodes.current;
    const handlers = nodes.map((_, index) => () => setOpen((current) => current.map((value, at) => value || at === index)));
    nodes.forEach((sets, index) => sets?.addEventListener('beforematch', handlers[index]));
    return () => nodes.forEach((sets, index) => sets?.removeEventListener('beforematch', handlers[index]));
  }, [folded]);

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
  const goTo = useCallback((index: number, behavior: ScrollBehavior = 'smooth') => {
    const node = section.current;
    const sticky = frame.current;
    if (!node || !sticky) return;
    const travel = node.offsetHeight - sticky.offsetHeight;
    const top = parseFloat(getComputedStyle(sticky).top) || 0;
    const start = node.getBoundingClientRect().top + window.scrollY - top;
    window.scrollTo({ top: start + ((index + 0.5) / PANELS.length) * travel, behavior });
  }, []);

  // Pinning makes the section taller after the first paint. A link to an anchor further down
  // the page (the persona pages link to #levels) has already been scrolled to by then, so the
  // target is scrolled to once more. Browsers without scroll anchoring would otherwise miss it.
  const settled = useRef(false);
  useEffect(() => {
    if (!pinned || settled.current) return;
    settled.current = true;
    const node = section.current;
    const target = window.location.hash ? document.getElementById(decodeURIComponent(window.location.hash.slice(1))) : null;
    if (node && target && !node.contains(target) && node.compareDocumentPosition(target) & Node.DOCUMENT_POSITION_FOLLOWING) {
      target.scrollIntoView();
    }
  }, [pinned]);

  // While pinned, the groups that are not showing are hidden "until found": the browser's
  // find-in-page still searches them, and a match brings its group forward. Where a browser
  // does not know that value, they are plainly hidden.
  useIsomorphicLayoutEffect(() => {
    const searchable = 'onbeforematch' in document.documentElement;
    panelNodes.current.forEach((panel, index) => {
      if (!panel) return;
      if (!pinned || index === active) panel.removeAttribute('hidden');
      else panel.setAttribute('hidden', searchable ? 'until-found' : '');
    });
  }, [pinned, active]);

  useEffect(() => {
    if (!pinned) return undefined;
    const nodes = panelNodes.current;
    const handlers = nodes.map((_, index) => () => goTo(index, 'auto'));
    nodes.forEach((panel, index) => panel?.addEventListener('beforematch', handlers[index]));
    return () => nodes.forEach((panel, index) => panel?.removeEventListener('beforematch', handlers[index]));
  }, [pinned, goTo]);

  // The frame keeps the height of the tallest group, so it does not jump between stages.
  useIsomorphicLayoutEffect(() => {
    const holder = panels.current;
    if (!holder) return undefined;
    if (!pinned) {
      holder.style.removeProperty('min-height');
      return undefined;
    }
    const measure = () => {
      const nodes = panelNodes.current.filter((panel): panel is HTMLDivElement => panel !== null);
      const hidden = nodes.map((panel) => panel.getAttribute('hidden'));
      nodes.forEach((panel) => panel.removeAttribute('hidden'));
      const tallest = Math.max(0, ...nodes.map((panel) => panel.offsetHeight));
      nodes.forEach((panel, index) => {
        const value = hidden[index];
        if (value !== null) panel.setAttribute('hidden', value);
      });
      holder.style.minHeight = `${tallest}px`;
      // The frame is one screen tall. If the tallest group, or the list beside it, needs more,
      // pinning would cut it off at both ends: the section goes back to the plain stacked list.
      const room = frame.current?.clientHeight ?? Number.POSITIVE_INFINITY;
      const needed = Math.max(tallest, aside.current?.offsetHeight ?? 0);
      if (needed > room) setFits(false);
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [pinned]);

  // A window that was too short for the pinned frame may fit it after a resize: try again then.
  useEffect(() => {
    if (!roomy || fits) return undefined;
    const retry = () => setFits(true);
    window.addEventListener('resize', retry);
    return () => window.removeEventListener('resize', retry);
  }, [roomy, fits]);

  return (
    <section
      ref={section}
      id="integrations"
      className={clsx(styles.section, pinned && styles.pinned)}
      style={{ '--steps': PANELS.length } as React.CSSProperties}
    >
      {/* Without script nothing can open a folded group, so nothing is folded */}
      <noscript>
        <style>{`.${styles.sets} { display: flex !important; }`}</style>
      </noscript>
      <div ref={frame} className={styles.frame}>
        {/* A floor of dots along the bottom edge; a ripple crosses it when the stage changes */}
        {pinned && <Floor stage={active} className={styles.floor} />}
        <div className={clsx('ak-container', styles.layout)}>
          <div ref={aside} className={styles.aside}>
            <SectionHeader
              index="03"
              label="Works with"
              title="Plug in what you already run"
              lead={`${ALL_ITEMS.length} integrations, and every one is an adapter. Swap one without touching the others.`}
            />

            {/* The stage list: shown only while the section is pinned. Its buttons move the page to
                a stage, so they are plain buttons with the current one marked, not tabs. */}
            <div className={styles.steps} role="group" aria-label="Integration groups">
              <span className={styles.marker} aria-hidden="true" />
              {PANELS.map((panel, index) => (
                <button
                  key={panel.id}
                  type="button"
                  aria-current={index === active ? 'true' : undefined}
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

          <div ref={panels} className={styles.panels}>
            {PANELS.map((panel, index) => {
              // Chips come in one after another across the whole panel, not set by set.
              let order = 0;
              return (
                <div
                  key={panel.id}
                  ref={(node) => {
                    panelNodes.current[index] = node;
                  }}
                  id={`integrations-panel-${panel.id}`}
                  className={clsx(styles.panel, index === active && styles.panelActive, open[index] && styles.panelOpen)}
                >
                  <p className={clsx('ak-label', styles.panelLabel)}>
                    <span className="ak-label__index">{String(index + 1).padStart(2, '0')}</span>
                    {panel.name}
                  </p>
                  <h3 className="ak-h3">
                    {folded ? (
                      <button
                        type="button"
                        className={styles.fold}
                        aria-expanded={open[index]}
                        aria-controls={`integrations-sets-${panel.id}`}
                        onClick={() => toggle(index)}
                      >
                        {panel.title}
                        <span className={styles.foldMeta} aria-hidden="true">
                          {panel.count}
                          <TbChevronDown className={styles.foldIcon} />
                        </span>
                      </button>
                    ) : (
                      panel.title
                    )}
                  </h3>
                  <div
                    ref={(node) => {
                      setNodes.current[index] = node;
                    }}
                    id={`integrations-sets-${panel.id}`}
                    className={styles.sets}
                  >
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
