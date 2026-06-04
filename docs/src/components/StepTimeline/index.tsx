import React, { useEffect, useRef, useState } from 'react';
import styles from './styles.module.css';
import { useHistory } from '@docusaurus/router';

interface StepDef {
  num: string;
  label: string;
  selector: string;
}

const LEVEL_STEPS: Record<string, StepDef[]> = {
  '01': [
    { num: '01', label: 'Identify the gap',   selector: '[data-step="bl-01"]' },
    { num: '02', label: 'Meet the solution',  selector: '[data-step="bl-02"]' },
    { num: '03', label: 'Agent Kernel',       selector: '[data-step="bl-03"]' },
    { num: '04', label: 'See it in action',   selector: '[data-step="bl-04"]' },
    { num: '05', label: 'How it works',       selector: '[data-step="bl-05"]' },
  ],
  '02': [
    { num: '01', label: 'Analogy',            selector: '[data-step="dev-01"]' },
    { num: '02', label: 'Architecture',       selector: '[data-step="dev-02"]' },
    { num: '03', label: 'Features',           selector: '[data-step="dev-03"]' },
    { num: '04', label: 'Framework',          selector: '[data-step="dev-04"]' },
    { num: '05', label: 'Complete picture',   selector: '[data-step="dev-05"]' },
  ],
  '03': [
    { num: '01', label: 'Analogy',            selector: '[data-step="ai-01"]' },
    { num: '02', label: 'Architecture',       selector: '[data-step="ai-02"]' },
    { num: '03', label: 'Stand out',          selector: '[data-step="ai-03"]' },
    { num: '04', label: 'Features',           selector: '[data-step="ai-04"]' },
    { num: '05', label: 'Framework',          selector: '[data-step="ai-05"]' },
    { num: '06', label: 'Build agents',       selector: '[data-step="ai-06"]' },
    { num: '07', label: 'Complete picture',   selector: '[data-step="ai-07"]' },
    { num: '08', label: 'OS depth',           selector: '[data-step="ai-08"]' },
  ],
};

const DEFAULT_THEME = {
  '--timeline-color': '#00ddff',
  '--timeline-color-glow': 'rgba(0, 221, 255, 0.5)',
  '--timeline-color-glow-strong': 'rgba(0, 221, 255, 0.8)',
  '--timeline-color-dark': '#0088cc',
  '--timeline-color-border': 'rgba(0, 221, 255, 0.25)',
  '--timeline-color-bg': 'rgba(0, 221, 255, 0.08)',
  '--timeline-color-bg-hover': 'rgba(0, 221, 255, 0.15)',
  '--timeline-color-text-dim': 'rgba(0, 221, 255, 0.7)',
};

const LEVEL_THEMES: Record<string, Record<string, string>> = {
  '01': { // Business Leader: Pink/Magenta (#D946EF)
    '--timeline-color': '#D946EF',
    '--timeline-color-glow': 'rgba(217, 70, 239, 0.5)',
    '--timeline-color-glow-strong': 'rgba(217, 70, 239, 0.8)',
    '--timeline-color-dark': '#9d17ab',
    '--timeline-color-border': 'rgba(217, 70, 239, 0.25)',
    '--timeline-color-bg': 'rgba(217, 70, 239, 0.08)',
    '--timeline-color-bg-hover': 'rgba(217, 70, 239, 0.15)',
    '--timeline-color-text-dim': 'rgba(217, 70, 239, 0.7)',
  },
  '02': { // Developer: Orange (#CC7D21)
    '--timeline-color': '#CC7D21',
    '--timeline-color-glow': 'rgba(204, 125, 33, 0.5)',
    '--timeline-color-glow-strong': 'rgba(204, 125, 33, 0.8)',
    '--timeline-color-dark': '#8b4d08',
    '--timeline-color-border': 'rgba(204, 125, 33, 0.25)',
    '--timeline-color-bg': 'rgba(204, 125, 33, 0.08)',
    '--timeline-color-bg-hover': 'rgba(204, 125, 33, 0.15)',
    '--timeline-color-text-dim': 'rgba(204, 125, 33, 0.7)',
  },
  '03': { // AI Engineer: Green (#03C540)
    '--timeline-color': '#03C540',
    '--timeline-color-glow': 'rgba(3, 197, 64, 0.5)',
    '--timeline-color-glow-strong': 'rgba(3, 197, 64, 0.8)',
    '--timeline-color-dark': '#017d27',
    '--timeline-color-border': 'rgba(3, 197, 64, 0.25)',
    '--timeline-color-bg': 'rgba(3, 197, 64, 0.08)',
    '--timeline-color-bg-hover': 'rgba(3, 197, 64, 0.15)',
    '--timeline-color-text-dim': 'rgba(3, 197, 64, 0.7)',
  },
};

interface StepTimelineProps {
  levelId: string | null;
  contentRef: React.RefObject<HTMLDivElement>;
}

export function StepTimeline({ levelId, contentRef }: StepTimelineProps) {
  const themeStyle = levelId ? (LEVEL_THEMES[levelId] ?? DEFAULT_THEME) : DEFAULT_THEME;
  const history = useHistory();
  const [activeStep, setActiveStep] = useState(0);
  const [visible, setVisible] = useState(false);
  const [connectorProgress, setConnectorProgress] = useState<number[]>([]);
  const rafRef = useRef<number | null>(null);
  const obsRef = useRef<IntersectionObserver | null>(null);
  const stepLayoutsRef = useRef<{ top: number; height: number }[]>([]);
  const [isNavbarVisible, setIsNavbarVisible] = useState(true);

  useEffect(() => {
    const navbar = document.querySelector('.navbar');
    if (!navbar) return;

    const updateVisibility = () => {
      const classes = Array.from(navbar.classList);
      const isHidden = classes.some(cls => cls.includes('navbarHidden') || cls === 'navbar--hidden');
      setIsNavbarVisible(!isHidden);
    };

    updateVisibility();

    const observer = new MutationObserver(updateVisibility);
    observer.observe(navbar, {
      attributes: true,
      attributeFilter: ['class'],
    });

    return () => observer.disconnect();
  }, []);

  const steps = levelId ? (LEVEL_STEPS[levelId] ?? []) : [];

  const getDocumentTop = (el: HTMLElement): number => {
    let top = 0;
    let node: HTMLElement | null = el;
    while (node) {
      top += node.offsetTop;
      node = node.offsetParent as HTMLElement | null;
    }
    return top;
  };

  useEffect(() => {
    obsRef.current?.disconnect();
    obsRef.current = null;

    if (!levelId || !contentRef.current) {
      setVisible(false);
      setActiveStep(0);
      return;
    }

    const el = contentRef.current;
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) { setVisible(true); setActiveStep(0); }
          else { setVisible(false); setActiveStep(0); }
        });
      },
      { root: null, threshold: 0.05 }
    );
    obs.observe(el);
    obsRef.current = obs;

    return () => { obs.disconnect(); obsRef.current = null; };
  }, [levelId, contentRef]);

  useEffect(() => {
    if (!visible || !contentRef.current || steps.length === 0) {
      setActiveStep(0);
      setConnectorProgress([]);
      stepLayoutsRef.current = [];
      return;
    }

    const els = steps.map(
      (s) => contentRef.current!.querySelector(s.selector) as HTMLElement | null
    );

    const measureLayouts = () => {
      stepLayoutsRef.current = els.map((el) => {
        if (!el) return { top: 0, height: 0 };
        return {
          top: getDocumentTop(el),
          height: el.offsetHeight,
        };
      });
    };

    const update = () => {
      const marker = window.innerHeight * 0.35;
      const scrollPos = window.scrollY + marker;
      let nextActive = 0;

      if (stepLayoutsRef.current.length === 0) {
        measureLayouts();
      }

      const next = stepLayoutsRef.current.map((layout, i) => {
        if (layout.height === 0) return 0;
        const top = layout.top;
        const bottom = top + layout.height;
        if (scrollPos >= top) nextActive = i;
        const start = top - marker;
        const end = bottom - marker;
        if (end <= start) return scrollPos >= end ? 1 : 0;
        return Math.max(0, Math.min(1, (scrollPos - start) / (end - start)));
      });

      setActiveStep(nextActive);
      setConnectorProgress(next);
      rafRef.current = null;
    };

    const onScroll = () => {
      if (rafRef.current != null) return;
      rafRef.current = window.requestAnimationFrame(update);
    };

    const onResize = () => {
      stepLayoutsRef.current = [];
      if (rafRef.current != null) return;
      rafRef.current = window.requestAnimationFrame(update);
    };

    // Initial measurement and render tick
    measureLayouts();
    update();

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onResize);

    return () => {
      if (rafRef.current) { window.cancelAnimationFrame(rafRef.current); rafRef.current = null; }
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onResize);
    };
  }, [visible, contentRef, steps]);

  const scrollToStep = (index: number) => {
    const el = contentRef.current?.querySelector(steps[index]?.selector) as HTMLElement | null;
    if (el) {
      const offset = isNavbarVisible ? 160 : 100;
      const top = el.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top, behavior: 'smooth' });
    }
  };

  if (steps.length === 0) return null;

  return (
    <nav
      className={`${styles.bar} ${visible ? styles['bar--visible'] : ''} ${isNavbarVisible ? styles['bar--navbar-visible'] : ''}`}
      aria-label="Section progress"
      style={themeStyle as React.CSSProperties}
    >
      <button
        className={styles.backBtn}
        onClick={() => {
          history.push('/');
          setTimeout(() => {
            document.getElementById('levels')?.scrollIntoView({ behavior: 'smooth' });
          }, 100);
        }}
        aria-label="Back to path selection"
        title="Back to path selection"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="25"
          height="25"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="15 18 9 12 15 6" />
        </svg>
      </button>

      <div className={styles.inner}>
        {steps.map((step, index) => {
          const state: 'done' | 'active' | 'upcoming' =
            index < activeStep ? 'done' : index === activeStep ? 'active' : 'upcoming';
          const connFill =
            index === 0
              ? 0
              : index - 1 < activeStep
              ? 1
              : index - 1 === activeStep
              ? (connectorProgress[index - 1] ?? 0)
              : 0;

          return (
            <React.Fragment key={step.num}>
              {index > 0 && (
                <div className={styles.connector} aria-hidden="true">
                  <div
                    className={styles.connectorFill}
                    style={{ '--fill': Math.max(0, Math.min(1, connFill)) } as React.CSSProperties}
                  />
                </div>
              )}

              <button
                className={`${styles.step} ${styles[`step--${state}`]}`}
                onClick={() => scrollToStep(index)}
                aria-label={`Step ${step.num}: ${step.label}`}
                aria-current={state === 'active' ? 'step' : undefined}
                title={step.label}
              >
                <span className={`${styles.num} ${styles[`num--${state}`]}`} aria-hidden="true">
                  {step.num}
                </span>

                <span className={`${styles.pip} ${styles[`pip--${state}`]}`} aria-hidden="true">
                </span>

                <span className={`${styles.label} ${styles[`label--${state}`]}`}>
                  {step.label}
                </span>
              </button>
            </React.Fragment>
          );
        })}
      </div>
    </nav>
  );
}