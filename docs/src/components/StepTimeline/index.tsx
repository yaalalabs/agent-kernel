import React, { useEffect, useRef, useState } from 'react';
import clsx from 'clsx';
import styles from './styles.module.css';

export type Step = {
  /** The `id` of the section this step links to. */
  id: string;
  /** One or two words, shown in the rail. */
  label: string;
};

type StepTimelineProps = {
  /** The steps of the page, in reading order. Pass a constant, not an array built on every render. */
  steps: readonly Step[];
  /** Accessible name of the navigation landmark. */
  label?: string;
};

/**
 * The step rail of a persona page: a numbered list of the page's sections that stays under the
 * navigation bar and marks the section being read. Each step is a plain link to its section, so
 * the rail works from the keyboard and without script; script only adds the marker.
 */
export function StepTimeline({ steps, label = 'Steps on this page' }: StepTimelineProps): JSX.Element {
  const [active, setActive] = useState(0);
  const list = useRef<HTMLOListElement>(null);

  // The step being read is the last section whose top has passed the upper third of the view.
  useEffect(() => {
    const sections = steps.map((step) => document.getElementById(step.id));
    let frame = 0;
    const update = () => {
      frame = 0;
      const line = window.innerHeight * 0.35;
      let current = 0;
      sections.forEach((section, index) => {
        if (section && section.getBoundingClientRect().top <= line) current = index;
      });
      setActive(current);
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
    };
  }, [steps]);

  // On a narrow screen the rail scrolls sideways: keep the marked step inside it.
  useEffect(() => {
    const rail = list.current;
    const item = rail?.children[active] as HTMLElement | undefined;
    if (!rail || !item || rail.scrollWidth <= rail.clientWidth) return;
    const left = item.offsetLeft - rail.offsetLeft - 24;
    rail.scrollTo({ left: Math.max(0, left), behavior: 'auto' });
  }, [active]);

  return (
    <nav className={styles.bar} aria-label={label}>
      <ol
        ref={list}
        className={clsx('ak-container', styles.list)}
        style={{ '--step-count': steps.length } as React.CSSProperties}
      >
        {steps.map((step, index) => (
          <li key={step.id} className={styles.item}>
            <a
              href={`#${step.id}`}
              className={clsx(styles.step, index === active && styles.stepActive)}
              aria-current={index === active ? 'step' : undefined}
            >
              <span className={styles.num} aria-hidden="true">
                {String(index + 1).padStart(2, '0')}
              </span>
              <span className={styles.name}>{step.label}</span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
